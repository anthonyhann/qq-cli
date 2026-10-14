"""search —— 跨会话搜索消息。"""

import click

from ..core.messages import (parse_time_range, search_messages,
                             validate_pagination)
from ..output.formatter import emit


@click.command("search")
@click.argument("keyword")
@click.option("--chat", "chats", multiple=True, help="限定会话（可多次指定）")
@click.option("--limit", default=20, help="返回条数")
@click.option("--offset", default=0, help="偏移量")
@click.option("--start-time", default="", help="起始时间")
@click.option("--end-time", default="", help="结束时间")
@click.option("--group-only", is_flag=True, help="只搜群聊")
@click.option("--private-only", is_flag=True, help="只搜私聊")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def search(ctx, keyword, chats, limit, offset, start_time, end_time,
           group_only, private_only, fmt):
    """在所有会话里搜索消息内容。

    \b
    示例:
      qq-cli search "家长"
      qq-cli search "作业" --chat "二年级六班家校群"
    """
    app = ctx.obj
    if not app.msg_db:
        raise click.ClickException("无法解密 nt_msg.db")

    validate_pagination(limit, offset)
    start_ts, end_ts = parse_time_range(start_time, end_time)

    peers = None
    if chats:
        peers = []
        for c in chats:
            g = app.resolve_group(c)
            if g:
                peers.append(g["group_id"])
            else:
                q = app.resolve_contact(c)
                if q is not None:
                    peers.append(q)

    conn = app.connect(app.msg_db)
    conns = []
    if not private_only:
        conns.append((conn, True))
    if not group_only:
        conns.append((conn, False))

    hits = search_messages(conns, keyword, limit=limit, offset=offset,
                           peers=peers or None, start_ts=start_ts, end_ts=end_ts)

    # 补上会话名
    for h in hits:
        h["chat"] = (app.group_name(h["peer"]) if h.get("is_group")
                     else app.name_for(h["peer"]))

    if fmt == "json":
        emit({"keyword": keyword, "count": len(hits), "messages": hits}, None, fmt)
    else:
        lines = [f"搜索 '{keyword}' 命中 {len(hits)} 条:", ""]
        for h in hits:
            lines.append(f"[{h['time']}] {h['chat']}: {h['text']}")
        emit(None, lambda _=None: "\n".join(lines), fmt)
