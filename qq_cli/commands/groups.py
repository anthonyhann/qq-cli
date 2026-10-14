"""groups / members —— 群列表与群成员。"""

import click

from ..output.formatter import emit, table


@click.command("groups")
@click.option("--limit", default=50, help="返回数量")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def groups(ctx, limit, fmt):
    """列出所有群组。"""
    app = ctx.obj
    items = app.groups[:limit]

    def render(rows):
        data = [[g["group_id"], g["name"], g["member_count"]] for g in rows]
        return table(data, ["群号", "群名", "成员数"])

    emit(items, render, fmt)


@click.command("members")
@click.argument("group")
@click.option("--limit", default=0, help="限制返回数量（0=全部）")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def members(ctx, group, limit, fmt):
    """列出某个群的成员。

    \b
    示例:
      qq-cli members "二年级六班家校群"
      qq-cli members 648974225 --limit 20
    """
    app = ctx.obj
    g = app.resolve_group(group)
    if not g:
        raise click.ClickException(f"找不到群: {group}")

    rows = app.members_of(g["group_id"])
    if limit:
        rows = rows[:limit]

    payload = {"group": g["name"], "group_id": g["group_id"],
               "member_count": g["member_count"], "count": len(rows),
               "members": rows}

    def render(p):
        data = [[m["qq"], m["name"], m["card"], m["role"]] for m in p["members"]]
        return (f"{p['group']}（{p['group_id']}）成员 {p['count']} 人\n"
                + table(data, ["QQ", "昵称", "群名片", "角色"]))

    emit(payload, render, fmt)
