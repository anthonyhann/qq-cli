"""qq-cli 入口 —— 查询本地 QQ (NT) 数据。"""

import sys

import click

from .core.context import AppContext

_VERSION = "0.1.0"


@click.group()
@click.version_option(version=_VERSION, prog_name="qq-cli")
@click.option("--config", "config_path", default=None,
              envvar="QQ_CLI_CONFIG", help="config.json 路径（默认自动查找）")
@click.pass_context
def cli(ctx, config_path):
    """QQ CLI — 查询本地 QQ 的消息、联系人、群组等数据。

    \b
    常用命令:
      qq-cli init --keys ~/all_keys.json     # 初始化并导入密钥
      qq-cli sessions --limit 10             # 最近会话
      qq-cli history "群名" --limit 20        # 聊天记录
      qq-cli search "关键词"                  # 搜索消息
      qq-cli groups                          # 群列表
      qq-cli members "群名"                   # 群成员
      qq-cli new-messages                    # 增量新消息
      qq-cli unread                          # 未读会话
    """
    if ctx.invoked_subcommand in ("init", "version", None):
        return
    try:
        ctx.obj = AppContext(config_path)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        click.echo(f"初始化失败: {e}", err=True)
        sys.exit(1)


from .commands.contacts import contacts
from .commands.export_media import export_media_cmd
from .commands.groups import groups, members
from .commands.history import history
from .commands.init import init
from .commands.keys import keys
from .commands.new_messages import new_messages, unread
from .commands.search import search
from .commands.sessions import sessions

cli.add_command(init)
cli.add_command(keys)
cli.add_command(sessions)
cli.add_command(history)
cli.add_command(search)
cli.add_command(contacts)
cli.add_command(groups)
cli.add_command(members)
cli.add_command(unread)
cli.add_command(new_messages)
cli.add_command(export_media_cmd)


if __name__ == "__main__":
    cli()
