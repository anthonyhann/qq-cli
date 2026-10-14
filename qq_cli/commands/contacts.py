"""contacts —— 好友查询。"""

import click

from ..output.formatter import emit, table


@click.command("contacts")
@click.option("--query", default="", help="按昵称/QQ 过滤")
@click.option("--detail", default="", help="查看某人详情")
@click.option("--limit", default=50, help="返回数量")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def contacts(ctx, query, detail, limit, fmt):
    """查询好友列表与详情。

    \b
    示例:
      qq-cli contacts --query 张
      qq-cli contacts --detail 675641
    """
    app = ctx.obj

    if detail:
        qq = app.resolve_contact(detail)
        if qq is None:
            raise click.ClickException(f"找不到联系人: {detail}")
        p = app.profiles.get(qq, {})
        payload = {"qq": qq, "name": app.name_for(qq),
                   "signature": p.get("signature", ""),
                   "is_buddy": qq in app.buddies}
        emit(payload, lambda x: "\n".join(
            f"{k}: {v}" for k, v in x.items()), fmt)
        return

    items = []
    for qq, b in app.buddies.items():
        name = b.get("name") or app.name_for(qq)
        if query and query.lower() not in name.lower() and query not in str(qq):
            continue
        items.append({"qq": qq, "name": name})
    items.sort(key=lambda x: x["name"])
    items = items[:limit]

    def render(p):
        data = [[r["qq"], r["name"]] for r in p["contacts"]]
        return table(data, ["QQ", "昵称"])

    emit({"count": len(items), "contacts": items}, render, fmt)
