"""联系人查询 —— profile_info.db。

实测：buddy_list 251 行（好友列表），profile_info_v6 3190 行（含陌生人，
只有出现在这里且有昵称的才作为姓名回退）。
"""

import sqlite3
from contextlib import closing

from .fields import B_QQ, B_UID, P_NICK, P_QQ, P_SIGN, col


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load_buddies(db_path):
    """好友列表 → {qq: {qq, uid}}。"""
    out = {}
    if not db_path:
        return out
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            rows = conn.execute(
                f'SELECT {col(B_QQ)}, {col(B_UID)} FROM "buddy_list"').fetchall()
        except sqlite3.Error:
            return out
        for qq_v, uid in rows:
            qq = _as_int(qq_v)
            if qq is None:
                continue
            out[qq] = {"qq": qq, "uid": (uid or "").strip(), "name": ""}
    return out


def load_profiles(db_path):
    """资料表 → {qq: {qq, name, signature}}。"""
    out = {}
    if not db_path:
        return out
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            rows = conn.execute(
                f'SELECT {col(P_QQ)}, {col(P_NICK)}, {col(P_SIGN)} '
                f'FROM "profile_info_v6"').fetchall()
        except sqlite3.Error:
            return out
        for qq_v, nick, sign in rows:
            qq = _as_int(qq_v)
            if qq is None:
                continue
            name = (nick or "").strip()
            out[qq] = {"qq": qq, "name": name,
                       "signature": (sign or "").strip()}
    return out


def merge_names(buddies, profiles):
    """把 profile 的昵称合并进好友表。"""
    for qq, b in buddies.items():
        p = profiles.get(qq)
        if p and p.get("name"):
            b["name"] = p["name"]
    return buddies
