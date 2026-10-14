"""QQ NT 各库的真实字段号（实测确认，非猜测）。

这些库的列名是数字字符串，语义需从样本反推。以下是本机实测结论：

group_info.db / group_list:
    60001 = 群号         60007 = 群名        60006 = 成员数
    60004 = 群主 UIN     60005 = 成员上限
group_info.db / group_member3:
    60001 = 群号         1002 = 成员 QQ     64003 = 群名片
    20002 = 成员昵称     1000 = NT UID      64002 = 角色
profile_info.db / buddy_list:
    1002 = 好友 QQ       1000 = NT UID      25007 = 关系
profile_info.db / profile_info_v6:
    1002 = QQ            20002 = 昵称       20011 = 个性签名
nt_msg.db / c2c_msg_table, group_msg_table:
    见 tables.py
"""

# group_list
G_GROUP_ID = "60001"
G_GROUP_NAME = "60007"
G_MEMBER_COUNT = "60006"
G_OWNER = "60004"
G_MAX_MEMBER = "60005"

# group_member3
M_GROUP_ID = "60001"
M_QQ = "1002"
M_NICK = "20002"
M_CARD = "64003"
M_ROLE = "64002"
M_UID = "1000"

# buddy_list
B_QQ = "1002"
B_UID = "1000"

# profile_info_v6
P_QQ = "1002"
P_NICK = "20002"
P_SIGN = "20011"
P_UID = "1000"


def col(name):
    return '"%s"' % name


def role_name(code):
    """64002 角色：实测 0=普通成员；群主/管理员需结合 64007 等判断，
    这里只区分已知值，未知返回空。"""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return ""
    return {0: "", 1: "群主", 2: "管理员"}.get(c, "")
