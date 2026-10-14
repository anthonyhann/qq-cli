"""unread / new-messages —— 未读会话与增量新消息。

状态文件 ~/.qq-cli/last_check.json 记录每个会话的最后时间戳，
删除该文件即可重置（下次调用会重新以「未读」为基线）。
"""

import json
import os

import click

from ..core.config import STATE_DIR
from ..core.messages import list_conversations
from ..output.formatter import emit, table

STATE_FILE = os.path.join(STATE_DIR, "last_check.json")


def _load():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def _snapshot(app):
    """当前所有会话的 (peer -> 最后时间戳) 快照。"""
    conn = app.connect(app.msg_db)
    out = {}
    for is_group in (False, True):
        for c in list_conversations(conn, is_group):
            peer = c["peer"]
            if peer in (0, "0", None):
                continue
            out[f"{'g' if is_group else 'c'}:{peer}"] = c["last_ts"] or 0
    return out


def _describe(app, key, ts):
    kind, peer = key.split(":", 1)
    is_group = kind == "g"
    try:
        peer_v = int(peer)
    except ValueError:
        peer_v = peer
    name = app.group_name(peer_v) if is_group else app.name_for(peer_v)
    from datetime import datetime
    return {"chat": name, "peer": peer_v, "is_group": is_group,
            "timestamp": ts,
            "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            if ts else ""}


@click.command("new-messages")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def new_messages(ctx, fmt):
    """获取自上次调用以来的新消息（增量）。

    \b
    首次调用：记录基线并返回当前所有活跃会话；
    后续调用：只返回基线之后有新消息的会话。
    状态文件: ~/.qq-cli/last_check.json（删除即重置）
    """
    app = ctx.obj
    if not app.msg_db:
        raise click.ClickException("无法解密 nt_msg.db")

    curr = _snapshot(app)
    last = _load()

    if not last:
        _save(curr)
        items = [_describe(app, k, v) for k, v in curr.items()]
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        payload = {"first_call": True, "new_count": len(items), "messages": items}
    else:
        items = []
        for k, v in curr.items():
            prev = last.get(k, 0)
            if v > prev:
                items.append(_describe(app, k, v))
        _save(curr)
        items.sort(key=lambda x: x["timestamp"])
        payload = {"first_call": False, "new_count": len(items), "messages": items}

    def render(p):
        if not p["messages"]:
            return "无新消息"
        return "\n".join(f"[{m['time']}] {m['chat']}" for m in p["messages"])

    emit(payload, render, fmt)


@click.command("unread")
@click.option("--limit", default=20, help="返回数量")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def unread(ctx, limit, fmt):
    """显示未读会话。

    \b
    说明：QQ 的未读数在 msg_unread_info_table 中，本命令基于
    「上次检查点之后有新消息的会话」推导，语义与 new-messages 首次调用相近。
    """
    app = ctx.obj
    if not app.msg_db:
        raise click.ClickException("无法解密 nt_msg.db")

    curr = _snapshot(app)
    last = _load()
    items = []
    for k, v in curr.items():
        prev = last.get(k, 0)
        if v > prev:
            items.append(_describe(app, k, v))
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    items = items[:limit]

    def render(rows):
        if not rows:
            return "无未读会话"
        data = [[r["chat"], r["time"]] for r in rows]
        return table(data, ["会话", "最后消息时间"])

    emit(items, render, fmt)
