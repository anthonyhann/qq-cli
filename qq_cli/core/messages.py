"""消息查询 —— 分区过滤、时间过滤、分页、Protobuf 正文解析。

设计要点（对齐 wechat-cli 已验证的做法）：
  - 跨分区/跨表取数时，先抓 limit+offset 条候选，再统一按时间排序分页，
    最后页内升序 —— 否则分页会漏或重复。
  - 解析失败不中断整条命令，逐条降级并记录 parse_status。
"""

import sqlite3
from contextlib import closing
from datetime import datetime

from . import tables as T
from .proto import extract_text

QUERY_LIMIT_MAX = 500
BATCH = 500


def _normalize_ts(ts):
    """QQ 的 40050 是秒级时间戳；稳妥起见兼容意外出现的毫秒值。"""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return 0
    if ts > 10_000_000_000:      # 毫秒
        ts //= 1000
    return ts


def _q(name):
    return '"%s"' % name


# ---------- 时间解析 ----------

def parse_time_value(value, field_name, is_end=False):
    value = (value or "").strip()
    if not value:
        return None
    for fmt, date_only in (("%Y-%m-%d %H:%M:%S", False),
                           ("%Y-%m-%d %H:%M", False),
                           ("%Y-%m-%d", True)):
        try:
            dt = datetime.strptime(value, fmt)
            if date_only and is_end:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(
        "%s 格式无效: %s。支持 YYYY-MM-DD / YYYY-MM-DD HH:MM / YYYY-MM-DD HH:MM:SS"
        % (field_name, value))


def parse_time_range(start_time="", end_time=""):
    s = parse_time_value(start_time, "start_time", is_end=False)
    e = parse_time_value(end_time, "end_time", is_end=True)
    if s is not None and e is not None and s > e:
        raise ValueError("start_time 不能晚于 end_time")
    return s, e


def validate_pagination(limit, offset=0, limit_max=QUERY_LIMIT_MAX):
    if limit <= 0:
        raise ValueError("limit 必须大于 0")
    if limit_max is not None and limit > limit_max:
        raise ValueError("limit 不能大于 %d" % limit_max)
    if offset < 0:
        raise ValueError("offset 不能小于 0")


# ---------- 会话（分区）枚举 ----------

def list_conversations(conn, is_group):
    """列出某张表里的所有会话分区。

    返回 [{peer, local_id, last_ts, count}]，peer 是对方 QQ 或群号。
    """
    table = T.table_for(is_group)
    peer, ts, local = T.F_PEER, T.F_TIME, T.F_LOCAL_ID
    sql = (f'SELECT {_q(local)}, {_q(peer)}, MAX({_q(ts)}), COUNT(*) '
           f'FROM {_q(table)} GROUP BY {_q(local)}, {_q(peer)} '
           f'ORDER BY MAX({_q(ts)}) DESC')
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for local_id, peer_v, last_ts, cnt in rows:
        out.append({"local_id": local_id, "peer": peer_v,
                    "last_ts": last_ts or 0, "count": cnt, "is_group": is_group})
    return out


# ---------- 消息读取 ----------

def _build_row(row, is_group, conn_names=None, members=None):
    """把一行消息转成统一 dict（顺序与 _select_sql 一致）。"""
    (msg_id, msg_type, direction, sender_qq, ts, body,
     sender_name, nick) = row
    ts = _normalize_ts(ts)
    text = extract_text(body)
    parse_ok = text is not None
    if text is None:
        text = "(无法解析)"
    name = ""
    if is_group:
        name = (sender_name or "").strip() or (nick or "").strip()
    if not name and members and sender_qq in members:
        name = members[sender_qq].get("card") or members[sender_qq].get("name") or ""
    return {
        "msg_id": msg_id,
        "timestamp": ts,
        "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "",
        "sender_qq": sender_qq,
        "sender": name or (str(sender_qq) if sender_qq else ""),
        "direction": T.direction_name(direction),
        "msg_type": T.msg_type_name(msg_type),
        "text": text,
        "parse_status": "ok" if parse_ok else "failed",
    }


# 顺序必须与 _build_row 的解包顺序严格一致
def _select_sql(is_group, where, order, with_peer=False):
    table = T.table_for(is_group)
    fields = (T.F_MSG_ID, T.F_MSG_TYPE, T.F_DIRECTION, T.F_SENDER,
              T.F_TIME, T.F_BODY, T.F_SENDER_NAME, T.F_NICK)
    cols = ", ".join(_q(c) for c in fields)
    if with_peer:
        cols += ", " + _q(T.F_PEER)
    return f'SELECT {cols} FROM {_q(table)} {where} ORDER BY {order}'


def query_messages(conn, is_group, peer=None, local_id=None,
                   start_ts=None, end_ts=None, limit=20, offset=0,
                   members=None, keyword=None):
    """按会话 + 时间范围查询消息，返回按时间升序的 dict 列表。"""
    where, params = [], []
    if peer is not None:
        where.append(f'{_q(T.F_PEER)} = ?')
        params.append(peer)
    if local_id is not None:
        where.append(f'{_q(T.F_LOCAL_ID)} = ?')
        params.append(local_id)
    if start_ts is not None:
        where.append(f'{_q(T.F_TIME)} >= ?')
        params.append(start_ts)
    if end_ts is not None:
        where.append(f'{_q(T.F_TIME)} <= ?')
        params.append(end_ts)
    if keyword:
        # 正文在 Protobuf 里，SQL 无法直接匹配 —— 先粗筛再用 Python 过滤
        pass

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = f'{_q(T.F_TIME)} DESC'

    # 多取一些候选，便于统一排序分页（keyword 过滤会剔除部分行）
    want = limit + offset
    fetch = max(want * (4 if keyword else 1), want)
    sql = _select_sql(is_group, clause, order) + " LIMIT ?"
    params_fetch = list(params) + [min(fetch, 5000)]
    try:
        rows = conn.execute(sql, params_fetch).fetchall()
    except sqlite3.Error:
        return []

    built = []
    for r in rows:
        item = _build_row(r, is_group, members=members)
        if keyword and keyword.lower() not in (item["text"] or "").lower():
            continue
        built.append(item)

    built.sort(key=lambda x: (x["timestamp"], x["msg_id"]), reverse=True)
    paged = built[offset:offset + limit]
    paged.sort(key=lambda x: (x["timestamp"], x["msg_id"]))
    return paged


def search_messages(conns, keyword, limit=20, offset=0, peers=None,
                    start_ts=None, end_ts=None, member_lookup=None):
    """跨会话搜索。conns = [(conn, is_group)]。"""
    hits = []
    for conn, is_group in conns:
        table = T.table_for(is_group)
        # 先按 peer 收窄
        where, params = [], []
        if peers:
            ph = ",".join("?" * len(peers))
            where.append(f'{_q(T.F_PEER)} IN ({ph})')
            params.extend(peers)
        if start_ts is not None:
            where.append(f'{_q(T.F_TIME)} >= ?')
            params.append(start_ts)
        if end_ts is not None:
            where.append(f'{_q(T.F_TIME)} <= ?')
            params.append(end_ts)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = (_select_sql(is_group, clause, f'{_q(T.F_TIME)} DESC',
                           with_peer=True) + " LIMIT 5000")
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            item = _build_row(r[:8], is_group)
            if keyword.lower() not in (item["text"] or "").lower():
                continue
            item["is_group"] = is_group
            item["peer"] = r[8]
            hits.append(item)

    hits.sort(key=lambda x: (x["timestamp"], x["msg_id"]), reverse=True)
    paged = hits[offset:offset + limit]
    paged.sort(key=lambda x: (x["timestamp"], x["msg_id"]))
    return paged
