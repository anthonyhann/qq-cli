"""端到端冒烟测试 —— 用真实 QQ 数据验证各层。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qq_cli.core.context import AppContext
from qq_cli.core.messages import list_conversations, query_messages, search_messages


def main():
    app = AppContext()
    print("=== 基础数据 ===")
    print("好友:", len(app.buddies))
    print("群:", len(app.groups))
    for g in app.groups[:6]:
        print("   %s  %-28s 成员=%d" % (g["group_id"], repr(g["name"])[:28],
                                        g["member_count"]))

    gid = app.groups[0]["group_id"]
    members = app.members_of(gid)
    print("\n群 %s 成员: %d" % (gid, len(members)))
    for m in members[:4]:
        print("   ", m)

    print("\n=== 名称解析 ===")
    for qq in list(app.buddies)[:3]:
        print("   %s -> %r" % (qq, app.name_for(qq)))

    print("\n=== 会话 ===")
    conn = app.connect(app.msg_db)
    for is_group in (False, True):
        convs = list_conversations(conn, is_group)
        label = "群" if is_group else "私聊"
        print("%s 会话: %d" % (label, len(convs)))
        for c in convs[:5]:
            peer = c["peer"]
            name = app.group_name(peer) if is_group else app.name_for(peer)
            print("   %s  last=%s  msgs=%d" % (name, c["last_ts"], c["count"]))

    print("\n=== 群消息 ===")
    target = None
    for c in list_conversations(conn, True):
        if c["count"] >= 5:
            target = c
            break
    if target:
        msgs = query_messages(conn, True, peer=target["peer"], limit=3)
        print("群 %s 最近 %d 条:" % (app.group_name(target["peer"]), len(msgs)))
        for m in msgs:
            print("   [%s] %s: %s" % (m["time"], m["sender"],
                                      (m["text"] or "")[:60].replace("\n", " ")))

    print("\n=== 搜索 ===")
    conns = [(conn, True), (conn, False)]
    hits = search_messages(conns, "家长", limit=3)
    print("搜 '家长': %d 条" % len(hits))
    for h in hits:
        print("   %s %s" % (h["time"], (h["text"] or "")[:60].replace("\n", " ")))


if __name__ == "__main__":
    main()
