"""密钥格式、路径校验与私有文件保存。

QQ NT 密钥为 16 字节 ASCII 字符串（不是微信那样的 32 字节 hex），
通过 lldb 断点从 nt_sqlite3_key_v2 的 x2(指针)/x3(长度) 读取。

密钥文件结构（~/.qq-cli/all_keys.json）：
    {
      "_note": "...",
      "nt_qq_<md5>/nt_db/nt_msg.db": {"enc_key": "16字节ASCII"}
    }
"""

import hashlib
import json
import ntpath
import os
import posixpath
import subprocess
import tempfile


def strip_key_metadata(keys):
    if not isinstance(keys, dict):
        raise ValueError("密钥文件必须是 JSON 对象")
    return {k: v for k, v in keys.items() if not k.startswith("_")}


def _is_safe_rel_path(path):
    if not isinstance(path, str) or not path or "\x00" in path:
        return False
    normalized = path.replace("\\", "/")
    return (not ntpath.splitdrive(normalized)[0]
            and not normalized.startswith("/")
            and ".." not in normalized.split("/")
            and posixpath.normpath(normalized) not in (".", ""))


def key_path_variants(rel_path):
    normalized = rel_path.replace("\\", "/")
    return list(dict.fromkeys((rel_path, normalized, normalized.replace("/", "\\"),
                               normalized.replace("/", os.sep))))


def get_key_info(keys, rel_path):
    if not _is_safe_rel_path(rel_path):
        return None
    for candidate in key_path_variants(rel_path):
        if candidate in keys and not candidate.startswith("_"):
            return keys[candidate]
    return None


def normalize_keys(keys):
    """规范化密钥；enc_key 必须是 1-64 字节的可打印 ASCII。"""
    result = {}
    for path, info in strip_key_metadata(keys).items():
        if not _is_safe_rel_path(path):
            raise ValueError("密钥文件包含非法数据库相对路径")
        key = info.get("enc_key") if isinstance(info, dict) else None
        if not isinstance(key, str) or not key:
            raise ValueError("密钥项缺少 enc_key")
        raw = key.encode("utf-8")
        if not 1 <= len(raw) <= 64:
            raise ValueError("enc_key 长度非法（应为 1-64 字节）")
        normalized = posixpath.normpath(path.replace("\\", "/"))
        if normalized in result and result[normalized]["enc_key"] != key:
            raise ValueError("同一数据库路径存在冲突密钥")
        result[normalized] = {"enc_key": key}
    return result


def load_keys(path):
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    if os.path.islink(path):
        raise ValueError("拒绝读取符号链接密钥文件")
    try:
        with open(path, encoding="utf-8") as handle:
            return normalize_keys(json.load(handle))
    except json.JSONDecodeError:
        raise ValueError("密钥文件 JSON 格式无效") from None


def find_key_for(all_keys, db_dir, rel_path):
    """按键的相对路径查找密钥。

    all_keys 的键可能是 "nt_qq_x/nt_db/nt_msg.db"，而调用方给的是
    相对 db_dir 的 "nt_msg.db"，这里两种形式都尝试。
    """
    info = get_key_info(all_keys, rel_path)
    if info:
        return info
    account = os.path.basename(os.path.dirname(os.path.realpath(db_dir)))
    if account:
        return get_key_info(all_keys, f"{account}/nt_db/{rel_path}")
    return None


def _restrict_file(path):
    if os.name == "nt":
        identity = subprocess.run(["whoami"], capture_output=True, text=True,
                                  check=True).stdout.strip()
        if not identity:
            raise RuntimeError("无法确定 Windows 当前身份")
        subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{identity}:(F)"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    else:
        os.chmod(path, 0o600)


def private_write_json(path, data, backup=True):
    """私有临时文件 + 原子替换；失败保留原文件。"""
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    if os.path.islink(path) or os.path.islink(parent):
        raise ValueError("拒绝写入符号链接目标")
    temporary = None
    backup_temp = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".qq-", dir=parent)
        os.close(fd)
        _restrict_file(temporary)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        if backup and os.path.exists(path):
            backup_path = path + ".bak"
            if os.path.islink(backup_path):
                raise ValueError("拒绝写入符号链接备份")
            fd, backup_temp = tempfile.mkstemp(prefix=".qq-backup-", dir=parent)
            os.close(fd)
            _restrict_file(backup_temp)
            with open(path, "rb") as source, open(backup_temp, "wb") as target:
                target.write(source.read())
                target.flush()
                os.fsync(target.fileno())
            os.replace(backup_temp, backup_path)
            backup_temp = None
        os.replace(temporary, path)
        temporary = None
    finally:
        for leftover in (temporary, backup_temp):
            if leftover is not None and os.path.exists(leftover):
                os.unlink(leftover)


def fingerprint_key(key):
    """密钥指纹（用于缓存目录命名，不泄露密钥本身）。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
