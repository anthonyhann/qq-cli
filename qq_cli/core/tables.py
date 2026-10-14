"""QQ NT 表结构常量与安全查询辅助。

实测确认的关键点：
  - 列名是**字符串数字**（"40050"），查询必须用双引号包裹，
    否则 40050 会被当成整数字面量返回（踩过这个坑）。
  - 两表共用编号体系，但部分字段语义不同（见注释）。
"""

C2C_TABLE = "c2c_msg_table"
GROUP_TABLE = "group_msg_table"

F_MSG_ID = "40001"        # 主键 / 全局消息 ID
F_SEQ = "40003"           # c2c: 全局倒序序号 / group: 群内序号
F_CHAT_TYPE = "40010"     # c2c=1, group=2
F_MSG_TYPE = "40011"      # 外层消息类型
F_DIRECTION = "40013"     # 0=收到, 1/2=本人发送, 3=系统
F_SENDER_UID = "40020"    # 发送者 NT UID
F_PEER_UID = "40021"      # 会话对象 UID（group 为群号字符串）
F_LOCAL_ID = "40027"      # 本地会话分区键
F_PEER = "40030"          # c2c: 对方 QQ / group: 群号
F_SENDER = "40033"        # 实际发送者 QQ
F_SENDER_NAME = "40090"   # group: 发送者群名片
F_TIME = "40050"          # 消息时间（Unix 秒）
F_DATE_IDX = "40058"      # 日期索引（UTC+8 当日零点）
F_NICK = "40093"          # 发送者昵称/备注
F_BODY = "40800"          # 消息体 Protobuf
F_REPLY_TO = "40850"      # c2c: Reaction 目标 / group: 被回复序号

MSG_TYPES = {
    1: "文本", 2: "图片", 3: "语音", 4: "视频", 5: "文件",
    6: "表情", 7: "位置", 8: "链接", 9: "名片", 10: "系统",
    11: "分享", 12: "合并转发", 13: "动画表情", 16: "通话",
}


def col(name):
    """把字段号包成可安全使用的列名。"""
    return '"%s"' % name


def table_for(is_group):
    return GROUP_TABLE if is_group else C2C_TABLE


def msg_type_name(code):
    if code is None:
        return "未知"
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "未知"
    if code in MSG_TYPES:
        return MSG_TYPES[code]
    if 100 <= code < 200:
        return "系统"
    return "type=%d" % code


def direction_name(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "未知"
    return {0: "收到", 1: "发送", 2: "发送", 3: "系统"}.get(code, "未知")
