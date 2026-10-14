"""应用上下文 —— 单例持有配置、缓存与解密后的库路径。"""

import os
import sqlite3

from .config import load_config, STATE_DIR
from .contacts import load_buddies, load_profiles, merge_names
from .db_cache import DBCache
from .groups import load_group_members, load_groups
from .key_utils import load_keys


class AppContext:
    """每次 CLI 调用初始化一次，被所有命令共享。"""

    def __init__(self, config_path=None):
        self.cfg = load_config(config_path)
        self.db_dir = self.cfg["db_dir"]
        self.account_dir = self.cfg.get("account_dir", "")
        self.keys_file = self.cfg["keys_file"]

        if not os.path.exists(self.keys_file):
            raise FileNotFoundError(
                "密钥文件不存在: %s\n"
                "请先运行: qq-cli init（需要提取密钥）" % self.keys_file)

        self.all_keys = load_keys(self.keys_file)
        self.cache = DBCache(self.all_keys, self.db_dir)

        os.makedirs(STATE_DIR, exist_ok=True)

        self._buddies = None
        self._profiles = None
        self._groups = None
        self._members_cache = {}

    # ---- 库路径 ----

    def _plain(self, rel):
        return self.cache.get(rel)

    @property
    def msg_db(self):
        return self._plain("nt_msg.db")

    @property
    def profile_db(self):
        return self._plain("profile_info.db")

    @property
    def group_db(self):
        return self._plain("group_info.db")

    # ---- 缓存数据 ----

    @property
    def buddies(self):
        if self._buddies is None:
            self._buddies = merge_names(load_buddies(self.profile_db),
                                        self.profiles)
        return self._buddies

    @property
    def profiles(self):
        if self._profiles is None:
            self._profiles = load_profiles(self.profile_db)
        return self._profiles

    @property
    def groups(self):
        if self._groups is None:
            self._groups = load_groups(self.group_db)
        return self._groups

    def members_of(self, group_id):
        if group_id not in self._members_cache:
            self._members_cache[group_id] = load_group_members(self.group_db, group_id)
        return self._members_cache[group_id]

    # ---- 名称解析 ----

    def name_for(self, qq):
        try:
            qq = int(qq)
        except (TypeError, ValueError):
            return str(qq)
        b = self.buddies.get(qq)
        if b and b.get("name"):
            return b["name"]
        p = self.profiles.get(qq)
        if p and p.get("name"):
            return p["name"]
        return str(qq)

    def group_name(self, group_id):
        for g in self.groups:
            if g["group_id"] == group_id:
                return g["name"] or str(group_id)
        return str(group_id)

    def resolve_group(self, name):
        """按群名或群号找群；返回 group dict 或 None。"""
        if name is None:
            return None
        s = str(name).strip()
        if s.isdigit():
            gid = int(s)
            for g in self.groups:
                if g["group_id"] == gid:
                    return g
            return {"group_id": gid, "name": self.group_name(gid),
                    "member_count": 0, "owner": ""}
        for g in self.groups:
            if g["name"] == s:
                return g
        for g in self.groups:
            if s and s in (g["name"] or ""):
                return g
        return None

    def resolve_contact(self, name):
        """按昵称/QQ 找好友，返回 qq 或 None。"""
        if name is None:
            return None
        s = str(name).strip()
        if s.isdigit():
            return int(s)
        for qq, b in self.buddies.items():
            if b.get("name") == s:
                return qq
        for qq, b in self.buddies.items():
            if s and s in (b.get("name") or ""):
                return qq
        for qq, p in self.profiles.items():
            if p.get("name") == s:
                return qq
        return None

    # ---- 连接 ----

    def connect(self, path):
        return sqlite3.connect(path)
