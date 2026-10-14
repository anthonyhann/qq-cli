"""keys —— 密钥管理。"""

import click

from ..core.config import KEYS_FILE, load_config
from ..core.crypto import verify_db_key
from ..core.key_utils import find_key_for, load_keys, strip_key_metadata
from ..output.formatter import emit, table


@click.group("keys")
def keys():
    """管理数据库密钥。"""


@keys.command("show")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
def show(fmt):
    """显示已配置的密钥条目（不打印密钥明文）。"""
    import os
    if not os.path.exists(KEYS_FILE):
        raise click.ClickException(f"密钥文件不存在: {KEYS_FILE}")
    data = strip_key_metadata(load_keys(KEYS_FILE))
    items = [{"db": k, "key_length": len(v["enc_key"])} for k, v in data.items()]
    emit({"keys_file": KEYS_FILE, "count": len(items), "entries": items},
         lambda p: "\n".join(f"{e['db']}  (密钥 {e['key_length']} 字节)"
                              for e in p["entries"]), fmt)


@keys.command("verify")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
def verify(fmt):
    """逐个校验密钥能否解开对应数据库。"""
    import os
    from ..core.config import NT_HEADER_SIZE

    cfg = load_config()
    keys = load_keys(cfg["keys_file"])
    rows = []
    for rel in ("nt_msg.db", "profile_info.db", "group_info.db",
                "recent_contact.db", "files_in_chat.db", "emoji.db"):
        path = os.path.join(cfg["db_dir"], rel)
        if not os.path.isfile(path):
            continue
        # 只有 1024 字节 = 空占位库（无数据），不算失败
        if os.path.getsize(path) <= NT_HEADER_SIZE:
            rows.append({"db": rel, "status": "empty"})
            continue
        info = find_key_for(keys, cfg["db_dir"], rel)
        if not info:
            rows.append({"db": rel, "status": "nokey"})
            continue
        ok = verify_db_key(path, info["enc_key"])
        rows.append({"db": rel, "status": "ok" if ok else "fail"})

    def render(p):
        icon = {"ok": "✅", "empty": "⬜", "nokey": "⚠️", "fail": "❌"}
        note = {"empty": "  (空库，无数据)", "nokey": "  (未配置密钥)"}
        return "\n".join(
            f"{icon.get(r['status'], '?')} {r['db']}{note.get(r['status'], '')}"
            for r in p)

    emit(rows, render, fmt)
