"""群与群成员 —— group_info.db 的 group_list / group_member3。

实测：group_list 27 群，group_member3 2945 行。
"""

import sqlite3
from contextlib import closing

from .fields import (G_GROUP_ID, G_GROUP_NAME, G_MAX_MEMBER, G_MEMBER_COUNT,
                     G_OWNER, M_CARD, M_GROUP_ID, M_NICK, M_QQ, M_ROLE, col)


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load_groups(db_path):
    """群列表 → [{group_id, name, member_count, owner}]，按成员数降序。"""
    out = []
    if not db_path:
        return out
    with closing(sqlite3.connect(db_path)) as conn:
        sql = (f'SELECT {col(G_GROUP_ID)}, {col(G_GROUP_NAME)}, '
               f'{col(G_MEMBER_COUNT)}, {col(G_OWNER)}, {col(G_MAX_MEMBER)} '
               f'FROM "group_list"')
        try:
            rows = conn.execute(sql).fetchall()
        except sqlite3.Error:
            return out
        for gid_v, name, cnt_v, owner_v, max_v in rows:
            gid = _as_int(gid_v)
            if gid is None:
                continue
            out.append({
                "group_id": gid,
                "name": (name or "").strip(),
                "member_count": _as_int(cnt_v) or 0,
                "owner": _as_int(owner_v) or 0,
                "max_member": _as_int(max_v) or 0,
            })
    out.sort(key=lambda x: (-x["member_count"], x["group_id"]))
    return out


def load_group_members(db_path, group_id):
    """某群成员 → [{qq, name, card, role}]。"""
    out = []
    if not db_path:
        return out
    with closing(sqlite3.connect(db_path)) as conn:
        sql = (f'SELECT {col(M_QQ)}, {col(M_NICK)}, {col(M_CARD)}, {col(M_ROLE)} '
               f'FROM "group_member3" WHERE {col(M_GROUP_ID)} = ?')
        try:
            rows = conn.execute(sql, (str(group_id),)).fetchall()
        except sqlite3.Error:
            return out
        for qq_v, nick, card, role in rows:
            qq = _as_int(qq_v)
            if qq is None:
                continue
            out.append({
                "qq": qq,
                "name": (nick or "").strip(),
                "card": (card or "").strip(),
                "role": _role(role),
            })
    return out


def _role(v):
    try:
        c = int(v)
    except (TypeError, ValueError):
        return ""
    return {1: "群主", 2: "管理员"}.get(c, "")
