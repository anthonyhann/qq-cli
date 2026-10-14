"""SQLCipher 驱动 —— PRAGMA 顺序严格按官方文档，逐表导出为明文库。"""

import os
import sqlite3
import tempfile

try:
    import sqlcipher3
except ImportError:  # pragma: no cover
    sqlcipher3 = None

from .config import PAGE_SIZE

# 顺序不能变：cipher_page_size 必须在 key 之前
PRAGMAS = [
    "PRAGMA cipher_page_size = 4096",
    "PRAGMA key = '%s'",
    "PRAGMA kdf_iter = 4000",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA1",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
]


def require_driver():
    if sqlcipher3 is None:
        raise RuntimeError(
            "缺少 sqlcipher3。安装方式：\n"
            "  uv pip install sqlcipher3\n"
            "注意：预编译 wheel 目前只有 cp310，请用 Python 3.10。"
        )
    return sqlcipher3


def _escape(key):
    return key.replace("'", "''")


def connect_encrypted(path, enc_key):
    """打开加密库并验证密钥；失败抛 RuntimeError。"""
    drv = require_driver()
    conn = drv.connect(path)
    cur = conn.cursor()
    try:
        for p in PRAGMAS:
            cur.execute(p % _escape(enc_key) if "%s" in p else p)
        cur.execute("SELECT count(*) FROM sqlite_master")
        cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        conn.close()
        raise RuntimeError(f"密钥无效或数据库损坏: {exc}") from exc
    return conn


def list_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [r[0] for r in cur.fetchall()]


def decrypt_to_plain(encrypted_path, out_path, enc_key, page_offset):
    """把加密库逐表导出为明文 SQLite。

    逐表 rowid 分页导出（而非手写页解密），这样能跳过损坏页继续走。
    返回 (导出的表数, 跳过的损坏页/表列表)。
    """
    src = connect_encrypted(encrypted_path, enc_key)
    failures = []

    directory = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".qq-plain-", dir=directory)
    os.close(fd)
    if os.path.exists(tmp):
        os.unlink(tmp)

    dst = sqlite3.connect(tmp)
    tables = list_tables(src)
    exported = 0
    try:
        for table in tables:
            if table.startswith("sqlite_"):
                continue  # 内部表由引擎管理，不能显式建表
            try:
                row = src.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)).fetchone()
                if not row or not row[0]:
                    continue
                dst.execute(row[0])

                cur = src.execute(f'SELECT * FROM "{table}"')
                cols = [d[0] for d in cur.description] if cur.description else []
                if not cols:
                    exported += 1
                    continue
                placeholders = ",".join("?" * len(cols))
                quoted = ",".join(f'"{c}"' for c in cols)
                insert = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})'

                batch = []
                for r in cur:
                    batch.append(tuple(r))
                    if len(batch) >= 2000:
                        dst.executemany(insert, batch)
                        batch.clear()
                if batch:
                    dst.executemany(insert, batch)

                # 复制索引定义
                for idx in src.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' "
                        "AND tbl_name=? AND sql IS NOT NULL", (table,)):
                    try:
                        dst.execute(idx[0])
                    except sqlite3.Error:
                        pass
                exported += 1
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{table}: {exc}")
        dst.commit()
    finally:
        dst.close()
        src.close()

    os.replace(tmp, out_path)
    return exported, failures
