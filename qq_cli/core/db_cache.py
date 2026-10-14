"""解密缓存 —— 按「账号目录 + 密钥 + 文件指纹」隔离明文库。

QQ 运行时会持续写 WAL，所以指纹必须包含 WAL 的状态；
否则会缓存住旧数据导致「查不到新消息」。
"""

import hashlib
import json
import os
import stat
import tempfile

from .crypto import is_encrypted_db, strip_nt_header, verify_db_key
from .key_utils import find_key_for, fingerprint_key

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "qq-cli")


def _private_directory(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
        raise ValueError("缓存目录不是当前用户拥有的真实目录")
    os.chmod(path, 0o700)


def _private_file(path):
    try:
        st = os.lstat(path)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or (hasattr(os, "getuid") and st.st_uid != os.getuid())):
            return False
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _stamp(path):
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("数据库不是普通文件")
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class DBCache:
    """把 nt_db/*.db 解密为明文库并缓存。

    命中条件：密钥指纹 + 主库/WAL 的 stat 指纹一致。
    """

    def __init__(self, all_keys, db_dir, cache_root=None):
        self._all_keys = all_keys
        self._db_dir = os.path.realpath(db_dir)
        self._cache_root = os.path.abspath(cache_root or CACHE_ROOT)
        _private_directory(self._cache_root)
        self._dir = None
        self._cache = {}

    def _namespace(self, key):
        identity = _digest([self._db_dir, fingerprint_key(key)])
        if identity != self._dir:
            self._dir = identity
            self._path = os.path.join(self._cache_root, identity)
            os.makedirs(self._path, mode=0o700, exist_ok=True)
            _private_directory(self._path)
            self._cache = {}
            self._load()
        return self._path

    def _meta_path(self):
        return os.path.join(self._path, "_meta.json")

    def _load(self):
        p = self._meta_path()
        if not _private_file(p):
            return
        try:
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict) and saved.get("version") == 1:
                entries = saved.get("entries")
                if isinstance(entries, dict):
                    self._cache = {k: v for k, v in entries.items()
                                   if isinstance(v, str)}
        except (ValueError, OSError):
            return

    def _save(self):
        tmp = None
        try:
            _private_directory(self._path)
            fd, tmp = tempfile.mkstemp(prefix=".meta-", dir=self._path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": self._cache}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._meta_path())
            tmp = None
        except OSError:
            pass
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def _source_fingerprint(self, db_path):
        parts = [os.path.basename(db_path), _stamp(db_path)]
        for suffix in ("-wal", "-shm"):
            p = db_path + suffix
            try:
                parts.append(_stamp(p))
            except (FileNotFoundError, ValueError):
                parts.append(None)
        return _digest(parts)

    def get(self, rel_key):
        """返回明文库路径；无密钥或文件不存在返回 None。"""
        db_path = os.path.join(self._db_dir, rel_key)
        if not os.path.isfile(db_path):
            return None

        info = find_key_for(self._all_keys, self._db_dir, rel_key)
        if not info:
            return None
        key = info["enc_key"]

        root = self._namespace(key)
        try:
            fingerprint = self._source_fingerprint(db_path)
        except (FileNotFoundError, ValueError):
            return None

        out = os.path.join(root, _digest([rel_key, fingerprint]) + ".db")
        if self._cache.get(rel_key) == fingerprint and _private_file(out):
            return out
        if os.path.exists(out) and self._cache.get(rel_key) == fingerprint:
            return out

        if not is_encrypted_db(db_path):
            # 未加密（例如已解密或空库），直接返回原路径
            return db_path

        if not verify_db_key(db_path, key):
            return None

        # 关键：SQLCipher 的 WAL 页同样是加密的，不能把原始帧直接写进明文库。
        # 正确做法是把「剥头后的主库 + 原始加密 WAL」放在一起交给 sqlcipher3，
        # 由它自己回放 WAL，再逐表导出为明文。
        import shutil

        from .sqlcipher import decrypt_to_plain

        work = os.path.join(root, ".work")
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, mode=0o700, exist_ok=True)
        staged = os.path.join(work, "staged.db")
        try:
            strip_nt_header(db_path, staged)
            for suffix in ("-wal", "-shm"):
                src = db_path + suffix
                if os.path.exists(src):
                    shutil.copy2(src, staged + suffix)

            plain = os.path.join(root, _digest([rel_key, fingerprint]) + ".db")
            tables, _failures = decrypt_to_plain(staged, plain, key, 0)
            if not tables:
                return None
        finally:
            shutil.rmtree(work, ignore_errors=True)

        self._cache[rel_key] = fingerprint
        self._save()
        return plain
