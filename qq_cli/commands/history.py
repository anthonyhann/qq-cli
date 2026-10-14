"""history —— 读取指定会话的聊天记录。"""

import click

from ..core.messages import (parse_time_range, query_messages,
                             validate_pagination)
from ..output.formatter import emit


@click.command("history")
@click.argument("chat")
@click.option("--limit", default=20, help="返回条数")
@click.option("--offset", default=0, help="偏移量")
@click.option("--start-time", default="", help="起始时间 YYYY-MM-DD [HH:MM[:SS]]")
@click.option("--end-time", default="", help="结束时间")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def history(ctx, chat, limit, offset, start_time, end_time, fmt):
    """读取某个会话的聊天记录。

    \b
    示例:
      qq-cli history "二年级六班家校群" --limit 20
      qq-cli history 648974225 --start-time 2026-10-13
    """
    app = ctx.obj
    if not app.msg_db:
        raise click.ClickException("无法解密 nt_msg.db")

    validate_pagination(limit, offset)
    start_ts, end_ts = parse_time_range(start_time, end_time)

    group = app.resolve_group(chat)
    is_group = group is not None
    if is_group:
        peer = group["group_id"]
        title = group["name"] or str(peer)
        members = None
    else:
        peer = app.resolve_contact(chat)
        if peer is None:
            raise click.ClickException(f"找不到会话: {chat}")
        title = app.name_for(peer)
        members = None

    conn = app.connect(app.msg_db)
    msgs = query_messages(conn, is_group, peer=peer, start_ts=start_ts,
                          end_ts=end_ts, limit=limit, offset=offset)
    for m in msgs:
        m["chat"] = title
        m["is_group"] = is_group

    if fmt == "json":
        emit({"chat": title, "is_group": is_group, "count": len(msgs),
              "messages": msgs}, None, fmt)
    else:
        lines = [f"{title} 最近 {len(msgs)} 条:", ""]
        for m in msgs:
            who = m["sender"] if is_group else m["direction"]
            lines.append(f"[{m['time']}] {who}: {m['text']}")
        emit(None, lambda _=None: "\n".join(lines), fmt)
