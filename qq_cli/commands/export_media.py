"""export-media —— 导出会话中的图片/文件附件。"""

import json
import os

import click

from ..core.media import export_media, render_index_md
from ..core.messages import parse_time_range
from ..output.formatter import emit, table


@click.command("export-media")
@click.argument("chat", required=False)
@click.option("--out", "out_dir", required=True, help="导出目录")
@click.option("--start-time", default="", help="起始时间 YYYY-MM-DD [HH:MM[:SS]]")
@click.option("--end-time", default="", help="结束时间")
@click.option("--kind", "kinds", multiple=True,
              type=click.Choice(["image", "video", "voice", "doc", "file"]),
              help="只导出指定类型（可多次）")
@click.option("--group-only", is_flag=True, help="只导出群聊附件")
@click.option("--private-only", is_flag=True, help="只导出私聊附件")
@click.option("--index/--no-index", default=True, help="生成 index.md")
@click.option("--report", "report_only", is_flag=True,
              help="只报告可导出/缺失情况，不复制文件")
@click.option("--orphans", is_flag=True,
              help="同时列出本地有但无消息引用的孤立文件")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["json", "text"]))
@click.pass_context
def export_media_cmd(ctx, chat, out_dir, start_time, end_time, kinds,
                     group_only, private_only, index, report_only, orphans,
                     fmt):
    """导出某个会话（或全部会话）的媒体附件。

    \b
    示例:
      qq-cli export-media "群名" --out ./export
      qq-cli export-media "群名" --out ./export --report
      qq-cli export-media 648974225 --start-time 2026-10-14 --out ./export

    \b
    注意: 只有已在 QQ 客户端中查看/下载过的媒体才在本地缓存中，
    未查看的附件无法导出，会在报告的 missing 中列出。
    """
    app = ctx.obj
    if not app.msg_db:
        raise click.ClickException("无法解密 nt_msg.db（密钥是否正确？）")

    start_ts, end_ts = parse_time_range(start_time, end_time)

    is_group = None
    if group_only:
        is_group = True
    elif private_only:
        is_group = False

    try:
        result = export_media(
            app, out_dir=out_dir, chat=chat, is_group=is_group,
            start_ts=start_ts, end_ts=end_ts,
            kinds=list(kinds) or None,
            include_orphans=orphans, dry_run=report_only)
    except ValueError as exc:
        raise click.ClickException(str(exc))

    if not report_only:
        os.makedirs(result["out_dir"], exist_ok=True)
        report_path = os.path.join(result["out_dir"], "export-report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        result["report_file"] = report_path

        if index:
            md_path = os.path.join(result["out_dir"], "index.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(render_index_md(result))
            result["index_file"] = md_path

    if fmt == "json":
        emit(result, None, fmt)
    else:
        emit(result, _render_text, fmt)


def _render_text(r):
    st = r["stats"]
    lines = []
    lines.append("媒体导出")
    lines.append("")
    lines.append("输出目录    : %s" % r["out_dir"])
    if r.get("chat"):
        lines.append("会话        : %s" % r["chat"])
    lines.append("扫描消息    : %d 条" % st["messages_scanned"])
    lines.append("声明附件    : %d 个" % st["attachments_declared"])
    lines.append("成功导出    : %d 个" % st["exported"])
    lines.append("未能导出    : %d 个" % st["missing"])
    lines.append("本地索引    : %d 文件 / %d 唯一 MD5" % (
        st["index"]["files"], st["index"]["unique_md5"]))
    lines.append("")

    if r["exported"]:
        lines.append("── 已导出 ──")
        rows = [[i["kind"], i["file"], "%dK" % (i["size"] // 1024)]
                for i in r["exported"]]
        lines.append(table(rows, ["类型", "文件", "大小"]))
        lines.append("")

    if r["missing"]:
        lines.append("── 未能导出（本地无缓存，需在 QQ 中查看该消息）──")
        rows = [[m["time"], m["sender"], m["filename"]] for m in r["missing"]]
        lines.append(table(rows, ["时间", "发送者", "文件"]))
        lines.append("")

    if r.get("index_file"):
        lines.append("索引: %s" % r["index_file"])
    if r.get("report_file"):
        lines.append("报告: %s" % r["report_file"])
    return "\n".join(lines)
