"""init —— 初始化配置与密钥导入。"""

import os

import click

from ..core.config import (CONFIG_FILE, KEYS_FILE, STATE_DIR,
                           auto_detect_account_dirs)
from ..core.crypto import verify_db_key
from ..core.key_utils import (find_key_for, load_keys, private_write_json,
                              strip_key_metadata)
from ..output.formatter import output


@click.command("init")
@click.option("--keys", "keys_path", default=None,
              help="导入已有的 all_keys.json")
@click.option("--account-dir", default=None,
              help="指定 QQ 账号数据目录（含 nt_db 的那层）")
@click.option("--key", default=None,
              help="直接提供 16 字节密钥（不推荐，会留在 shell 历史里）")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
def init(keys_path, account_dir, key, fmt):
    """初始化 qq-cli：定位账号目录、导入密钥并校验。

    \b
    示例:
      qq-cli init --keys ~/all_keys.json
      qq-cli init --account-dir "~/Library/Application Support/QQ/nt_qq_xxx"
    """
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)

    # 定位账号目录
    if account_dir:
        acct = os.path.abspath(os.path.expanduser(account_dir))
        if not os.path.isdir(os.path.join(acct, "nt_db")):
            raise click.ClickException(f"目录下没有 nt_db: {acct}")
    else:
        cands = auto_detect_account_dirs()
        if not cands:
            raise click.ClickException(
                "未找到 QQ 数据目录。请确认 QQ 已安装并登录过。")
        acct = cands[0]

    db_dir = os.path.join(acct, "nt_db")
    acct_name = os.path.basename(acct)

    # 准备密钥
    keys = {}
    if keys_path:
        keys = strip_key_metadata(load_keys(keys_path))
    elif key:
        keys = {f"{acct_name}/nt_db/nt_msg.db": {"enc_key": key}}

    verified = []
    if keys:
        for rel in ("nt_msg.db", "profile_info.db", "group_info.db"):
            p = os.path.join(db_dir, rel)
            info = find_key_for(keys, db_dir, rel)
            if not info or not os.path.isfile(p):
                continue
            if verify_db_key(p, info["enc_key"]):
                verified.append(rel)

    if keys:
        merged = {}
        if os.path.exists(KEYS_FILE):
            try:
                merged = strip_key_metadata(load_keys(KEYS_FILE))
            except ValueError:
                merged = {}
        merged.update(keys)
        private_write_json(KEYS_FILE, merged)

    cfg = {"account_dir": acct, "db_dir": db_dir,
           "keys_file": KEYS_FILE, "decrypted_dir": os.path.join(STATE_DIR, "decrypted")}
    private_write_json(CONFIG_FILE, cfg, backup=False)

    payload = {
        "account_dir": acct,
        "db_dir": db_dir,
        "config_file": CONFIG_FILE,
        "keys_file": KEYS_FILE,
        "keys_imported": len(keys),
        "verified_databases": verified,
    }

    if fmt == "json":
        output(payload, "json")
    else:
        lines = ["初始化完成", "",
                 f"账号目录: {acct}",
                 f"数据库目录: {db_dir}",
                 f"配置文件: {CONFIG_FILE}"]
        if keys:
            lines.append(f"密钥条目: {len(keys)}")
            lines.append(f"密钥校验通过: {', '.join(verified) if verified else '无'}")
        else:
            lines.append("未提供密钥。请先用 lldb 提取密钥后运行:")
            lines.append("  qq-cli init --keys <all_keys.json>")
        output("\n".join(lines), "text")
