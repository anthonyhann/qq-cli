"""QQ NT 数据库解密 —— SQLCipher 4，带 1024 字节 NT 自定义头。

实测确认（macOS 26.6 / QQ 7.0.2）：
  - 文件头 16 字节为 "SQLite header 3\\x00"（伪装头，非标准 "SQLite format 3"）
  - 真正的 SQLCipher 数据从 offset 1024 开始
  - 校验: (filesize - 1024) % 4096 == 0
  - WAL:  (walsize - 32) % (24 + 4096) == 0

SQLCipher 参数（顺序不能错）：
    PRAGMA cipher_page_size = 4096;        # 必须在 key 之前
    PRAGMA key = '<16字节ASCII>';
    PRAGMA kdf_iter = 4000;
    PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
    PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
"""

import hashlib
import hmac
import os
import shutil
import struct
import tempfile

from .config import NT_HEADER_SIZE, PAGE_SIZE

SALT_SZ = 16
HMAC_SZ = 20          # HMAC_SHA1
KEY_SZ = 32
KDF_ITER = 4000
SQLITE_HDR = b"SQLite format 3\x00"
NT_MAGIC = b"SQLite header 3\x00"

WAL_HEADER_SZ = 32
WAL_FRAME_HEADER_SZ = 24
WAL_FRAME_SZ = WAL_FRAME_HEADER_SZ + PAGE_SIZE


def is_encrypted_db(path):
    """是否为 QQ NT 加密库（有 NT 伪装头且非明文 SQLite）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    if head == SQLITE_HDR:
        return False
    if head == NT_MAGIC:
        return True
    return head.startswith(b"SQLite header")


def strip_nt_header(src, dst=None):
    """剥离 1024 字节 NT 头；返回 (dst_or_None, payload_size)。src 不变。"""
    size = os.path.getsize(src)
    if size <= NT_HEADER_SIZE:
        raise ValueError(f"数据库过小，无法剥离 NT 头: {src}")
    payload = size - NT_HEADER_SIZE
    if payload % PAGE_SIZE:
        raise ValueError(
            f"剥离 NT 头后长度不是 4096 的整数倍: {payload}（WAL 未合并或文件损坏）")
    if dst is None:
        return None, payload

    directory = os.path.dirname(os.path.abspath(dst))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".qq-clear-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as fin:
            fin.seek(NT_HEADER_SIZE)
            shutil.copyfileobj(fin, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dst, payload


def derive_mac_key(enc_key, salt):
    """SQLCipher 4 HMAC 密钥：PBKDF2-HMAC-SHA512(mac_salt = salt ^ 0x3A, 4000)。"""
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key.encode("utf-8"), mac_salt,
                               KDF_ITER, dklen=KEY_SZ)


def verify_key(enc_key, page1):
    """用 page1 尾部 HMAC-SHA1 校验密钥。page1 必须是剥离 NT 头后的第一页。"""
    if len(page1) != PAGE_SIZE:
        return False
    salt = page1[:SALT_SZ]
    mac_key = derive_mac_key(enc_key, salt)
    hm = hmac.new(mac_key, page1[SALT_SZ:PAGE_SIZE - HMAC_SZ], hashlib.sha1)
    hm.update(struct.pack("<I", 1))
    return hmac.compare_digest(hm.digest(), page1[PAGE_SIZE - HMAC_SZ:])


def verify_db_key(src, enc_key):
    """校验密钥是否能打开该库。

    优先用 sqlcipher3 实际打开（权威）；不可用时退回 HMAC 校验
    （SQLCipher 内部派生细节跨版本有差异，HMAC 仅作启发式）。
    """
    # HMAC 启发式（快速、不需落盘）
    try:
        with open(src, "rb") as f:
            f.seek(NT_HEADER_SIZE)
            page1 = f.read(PAGE_SIZE)
        if verify_key(enc_key, page1):
            return True
    except OSError:
        return False
    # HMAC 不匹配不代表密钥错（派生细节可能有差异），用 driver 定论
    try:
        import sqlcipher3  # noqa: F401
    except ImportError:
        return False
    import tempfile
    from .sqlcipher import connect_encrypted
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".qq-probe-", suffix=".db")
        os.close(fd)
        strip_nt_header(src, tmp)
        conn = connect_encrypted(tmp, enc_key)
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _file_stamp(f):
    st = os.fstat(f.fileno())
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _wal_checksum(data, byte_order, seed=(0, 0)):
    s1, s2 = seed
    for x1, x2 in struct.iter_unpack(byte_order + "II", data):
        s1 = (s1 + x1 + s2) & 0xFFFFFFFF
        s2 = (s2 + x2 + s1) & 0xFFFFFFFF
    return s1, s2


def read_wal_pages(wal_path):
    """读取 WAL 中所有有效帧，返回 {pgno: page_bytes}（后者覆盖前者）。

    QQ 运行时新消息可能只在 WAL 里，必须合并才能看到最新数据。
    只做结构校验（magic/页大小/salt 一致），不做滚动 checksum 校验——
    QQ 的 WAL 由 SQLCipher 生成，校验和以客户端字节序计算，跨实现校验易误判。
    """
    if not os.path.exists(wal_path):
        return {}
    size = os.path.getsize(wal_path)
    if size == 0:
        return {}
    if size < WAL_HEADER_SZ or (size - WAL_HEADER_SZ) % WAL_FRAME_SZ:
        raise ValueError("WAL 结构不完整（头部或帧长度非法）")

    pages = {}
    with open(wal_path, "rb") as wf:
        hdr = wf.read(WAL_HEADER_SZ)
        magic, version, page_size = struct.unpack(">III", hdr[:12])
        if magic not in (0x377F0682, 0x377F0683):
            raise ValueError("WAL magic 非法")
        if page_size != PAGE_SIZE:
            raise ValueError(f"WAL 页大小不是 {PAGE_SIZE}")
        salt = hdr[16:24]
        for _ in range((size - WAL_HEADER_SZ) // WAL_FRAME_SZ):
            fh = wf.read(WAL_FRAME_HEADER_SZ)
            page = wf.read(PAGE_SIZE)
            if len(fh) != WAL_FRAME_HEADER_SZ or len(page) != PAGE_SIZE:
                break
            if fh[8:16] != salt:
                break
            pgno = struct.unpack(">I", fh[:4])[0]
            if not 0 < pgno <= 0xFFFFFFFE:
                continue
            pages[pgno] = page
    return pages


def apply_wal(plain_db, wal_path):
    """把 WAL 的有效帧写入已解密的明文库（就地）。返回应用的页数。"""
    pages = read_wal_pages(wal_path)
    if not pages:
        return 0
    applied = 0
    with open(plain_db, "r+b") as f:
        for pgno, page in pages.items():
            f.seek((pgno - 1) * PAGE_SIZE)
            f.write(page)
            applied += 1
        f.flush()
        os.fsync(f.fileno())
    return applied
