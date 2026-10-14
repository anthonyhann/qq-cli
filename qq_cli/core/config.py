"""配置加载 — 从 ~/.qq-cli/ 读取自包含配置。

QQ NT 数据目录布局（实测 macOS 26.x / QQ 7.0.2）：

  沙盒容器（官方签名）:
    ~/Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ/
  非沙盒（ad-hoc 副本）:
    ~/Library/Application Support/QQ/

两者下都是 nt_qq_<md5>/nt_db/ 结构。多账号时会有多个 nt_qq_* 目录。
"""

import glob as glob_mod
import json
import os
import platform
import sys

_SYSTEM = platform.system().lower()

if _SYSTEM == "darwin":
    _DEFAULT_PROCESS = "QQ"
elif _SYSTEM == "linux":
    _DEFAULT_PROCESS = "qq"
else:
    _DEFAULT_PROCESS = "QQ.exe"

STATE_DIR = os.path.expanduser("~/.qq-cli")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
KEYS_FILE = os.path.join(STATE_DIR, "all_keys.json")

# NT 自定义头部长度：真正的 SQLCipher 数据从 1024 字节之后开始
NT_HEADER_SIZE = 1024
PAGE_SIZE = 4096

QQ_DATA_ROOTS = [
    # ad-hoc 重签名（非沙盒）——副本路线走这里
    "~/Library/Application Support/QQ",
    # 官方沙盒容器
    "~/Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ",
]


def _choose_candidate(candidates):
    """多个账号目录时让用户选择；非交互环境报错而非猜。"""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if not sys.stdin.isatty():
        raise ValueError(
            "检测到多个 QQ 账号数据目录，非交互环境不会自动选择。\n"
            "请通过 --db-dir 明确指定：\n  " + "\n  ".join(candidates)
        )
    print("[!] 检测到多个 QQ 数据目录:")
    for i, c in enumerate(candidates, 1):
        print(f"    {i}. {c}")
    print("    0. 跳过")
    try:
        while True:
            choice = input(f"请选择 [0-{len(candidates)}]: ").strip()
            if choice == "0":
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                return candidates[int(choice) - 1]
            print("    无效输入")
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def auto_detect_account_dirs():
    """列出所有 nt_qq_* 账号目录（按最近活动排序）。"""
    seen, out = set(), []
    for root in QQ_DATA_ROOTS:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        for match in sorted(glob_mod.glob(os.path.join(root, "nt_qq_*"))):
            if not os.path.isdir(match):
                continue
            real = os.path.realpath(match)
            if real in seen:
                continue
            seen.add(real)
            out.append(real)

    def _mtime(path):
        target = os.path.join(path, "nt_db")
        if not os.path.isdir(target):
            target = path
        try:
            return os.path.getmtime(target)
        except OSError:
            return 0

    out.sort(key=_mtime, reverse=True)
    return out


def load_config(config_path=None):
    """加载配置。默认 ~/.qq-cli/config.json。"""
    if config_path is None:
        config_path = CONFIG_FILE

    cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            cfg = {}

    account_dir = cfg.get("account_dir", "")
    if not account_dir:
        detected = _choose_candidate(auto_detect_account_dirs())
        if detected:
            cfg["account_dir"] = detected
        else:
            raise FileNotFoundError(
                "未找到 QQ 数据目录。\n"
                "请确认 QQ 已安装并登录过，或运行: qq-cli init"
            )

    db_dir = cfg.get("db_dir", "")
    if not db_dir:
        db_dir = os.path.join(cfg["account_dir"], "nt_db")
    cfg["db_dir"] = db_dir

    state_dir = os.path.dirname(os.path.abspath(config_path))
    cfg.setdefault("keys_file", os.path.join(state_dir, "all_keys.json"))
    cfg.setdefault("decrypted_dir", os.path.join(state_dir, "decrypted"))
    cfg.setdefault("qq_process", _DEFAULT_PROCESS)

    for key in ("account_dir", "db_dir", "keys_file", "decrypted_dir"):
        if key in cfg and not os.path.isabs(cfg[key]):
            cfg[key] = os.path.join(state_dir, cfg[key])

    return cfg
