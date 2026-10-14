"""输出格式化 —— JSON（默认，面向 AI Agent）/ text（面向人）。"""

import json
import sys

import click


def output(data, fmt="json"):
    if fmt == "json":
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        click.echo(data)


def emit(payload, text_renderer, fmt="json"):
    """payload 为结构化数据，text_renderer 负责渲染纯文本。"""
    if fmt == "json":
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(text_renderer(payload))


def table(rows, headers):
    """简易等宽表格（中文按 2 宽度计）。"""
    def w(s):
        return sum(2 if ord(c) > 0x2E80 else 1 for c in str(s))

    widths = [w(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], w(c))
    lines = []
    lines.append("  ".join(str(h) + " " * (widths[i] - w(h))
                           for i, h in enumerate(headers)))
    lines.append("  ".join("-" * x for x in widths))
    for r in rows:
        lines.append("  ".join(str(c) + " " * (widths[i] - w(c))
                               for i, c in enumerate(r)))
    return "\n".join(lines)
