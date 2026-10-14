"""sessions —— 最近会话列表。"""

import click

from ..core.messages import list_conversations
from ..output.formatter import emit, table


@click.command("sessions")
@click.option("--limit", default=20, help="返回的会话数量")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def sessions(ctx, limit, fmt):
    """获取最近会话列表（私聊 + 群聊合并，按时间排序）。"""
    app = ctx.obj
    if not app.msg_db:
        raise click.ClickException("无法解密 nt_msg.db（密钥是否正确？）")

    conn = app.connect(app.msg_db)
    items = []
    for is_group in (False, True):
        for c in list_conversations(conn, is_group):
            peer = c["peer"]
            if is_group:
                name = app.group_name(peer)
                chat_type = "群"
            else:
                name = app.name_for(peer)
                chat_type = "私聊"
            if peer in (0, "0", None):
                continue          # 系统占位分区
            items.append({
                "chat": name,
                "peer": peer,
                "is_group": is_group,
                "chat_type": chat_type,
                "message_count": c["count"],
                "last_timestamp": c["last_ts"],
                "last_time": _fmt(c["last_ts"]),
            })

    items.sort(key=lambda x: x["last_timestamp"], reverse=True)
    items = items[:limit]

    def render(rows):
        data = [[r["chat_type"], r["chat"], r["message_count"], r["last_time"]]
                for r in rows]
        return table(data, ["类型", "会话", "消息数", "最后时间"])

    emit(items, render, fmt)


def _fmt(ts):
    from datetime import datetime
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
