# QQ CLI

> 命令行查询本地 QQ (NT) 数据 —— 专为 AI Agent 集成设计。

<p>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.10-3776ab.svg"></a>
  <a href="https://github.com/anthonyhann/qq-cli/releases"><img alt="Release" src="https://img.shields.io/github/v/release/anthonyhann/qq-cli?color=green"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-lightgrey.svg">
  <img alt="Read only" src="https://img.shields.io/badge/access-read--only-success.svg">
</p>

聊天记录 · 会话 · 群组 · 群成员 · 联系人 · 未读 · 增量新消息

**[English](README.md)**

---

## 为什么需要它

QQ NT 把聊天记录存在本机的 **SQLCipher 加密 SQLite** 里，官方没有提供本地 API。
QQ CLI 以**只读**方式解密，并把数据以结构化 JSON 暴露出来，
让 Agent 和脚本可以直接查询，而不必去抓取界面。

- **全程本地** —— 无任何网络请求
- **只读** —— 不修改、不发送、不删除任何消息
- **面向 Agent** —— 默认 JSON 输出，字段名稳定

## 功能

| 命令 | 说明 |
|---|---|
| `sessions` | 最近会话（私聊 + 群聊按时间合并） |
| `history` | 指定会话的聊天记录（支持时间范围与分页） |
| `search` | 跨会话全文搜索 |
| `groups` | 群组列表（含成员数） |
| `members` | 群成员（QQ / 昵称 / 群名片 / 角色） |
| `contacts` | 好友列表与资料查询 |
| `unread` | 有新消息的会话 |
| `new-messages` | 增量新消息（状态持久化） |
| `keys` | 密钥管理与校验 |
| `init` | 定位账号目录、导入并校验密钥 |

## 环境要求

- macOS（Apple Silicon 或 Intel）
- QQ NT 桌面客户端，已安装并至少登录过一次
- **Python 3.10** —— `sqlcipher3` 目前只提供 cp310 预编译 wheel

## 安装

```bash
# 1. 创建独立 venv（必须 3.10）
uv venv --python 3.10 ~/.qq-cli-venv

# 2. 从公网 PyPI 安装依赖
export UV_INDEX_URL=https://pypi.org/simple/
uv pip install --python ~/.qq-cli-venv/bin/python click sqlcipher3

# 3. 安装 QQ CLI
uv pip install --python ~/.qq-cli-venv/bin/python git+https://github.com/anthonyhann/qq-cli.git

# 4. 加入 PATH
ln -sfn ~/.qq-cli-venv/bin/qq-cli ~/.local/bin/qq-cli
```

> 若使用企业内网镜像且其中没有 `sqlcipher3`，必须加 `--index-url https://pypi.org/simple/`。

## 快速开始

### 1. 提取数据库密钥

QQ 的密钥是一个 **16 字节 ASCII 字符串**，存在于 QQ 进程内存中。
它通过在 `nt_sqlite3_key_v2` 函数入口下断点，读取 `x2`（指针）/ `x3`（长度）寄存器获得。

由于官方 QQ 启用 hardened runtime，`lldb` **无法 attach**。
安全做法是**在副本上操作** —— 原始 QQ.app 全程不被修改：

```bash
# 复制 QQ 并改用独立 bundle id（获得独立容器）
cp -R /Applications/QQ.app /tmp/qqrun/QQ.app
plutil -replace CFBundleIdentifier -string com.tencent.qq.debugrun \
    /tmp/qqrun/QQ.app/Contents/Info.plist
codesign --force --deep --sign - /tmp/qqrun/QQ.app
open /tmp/qqrun/QQ.app
```

然后 attach 并布下断点：

```bash
PID=$(pgrep -f 'qqrun/QQ.app/Contents/MacOS/QQ$')
lldb -p "$PID" --one-line "command script import $PWD/scripts/extract_key.py"
#   (lldb) image list -o -f | grep wrapper.node   # 确认模块已加载
#   (lldb) qq-arm                               # 自动计算断点地址
#   (lldb) c                                      # 然后在 QQ 里点击「登录」
#   → 密钥自动打印
```

`scripts/regdump.py` 会在断点处 dump 全部寄存器 —— 这是确认**哪两个寄存器**
承载指针与长度的可靠方法（不同 QQ 版本寄存器约定可能不同）。

> **警告：** `--deep` 签名会重写嵌套 helper bundle（`QQ Helper.app`）的签名。
> 对**已安装的** QQ.app 这样做会导致 GPU 进程崩溃、QQ 无法启动。
> 请务必只在副本上操作。

### 2. 初始化

```bash
qq-cli init --keys ~/all_keys.json
qq-cli keys verify
```

### 3. 查询

```bash
qq-cli sessions --limit 10
qq-cli history "群名称" --limit 20
qq-cli search "关键词" --chat "群名称"
qq-cli members "群名称" --limit 20
qq-cli new-messages            # 首次为基线，之后返回增量
```

所有命令都支持 `--format json`（默认）与 `--format text`。

## 原理

QQ NT 的数据库**不是**普通 SQLite，磁盘布局如下：

```
偏移 0..15      "SQLite header 3\x00"   ← 伪装头，并非 "SQLite format 3"
偏移 16..1023   NT 元数据块
偏移 1024..     SQLCipher 4 数据页
```

`(文件大小 - 1024) % 4096 == 0` —— 已在 `nt_msg.db`、`group_info.db`、
`profile_info.db` 以及 WAL 文件上逐一验证。

处理流程：

1. **剥离** 1024 字节 NT 头
2. **解密**（SQLCipher 4）—— PRAGMA 顺序不能错：
   ```
   PRAGMA cipher_page_size = 4096;        -- 必须在 key 之前
   PRAGMA key = '<16字节 ASCII>';
   PRAGMA kdf_iter = 4000;
   PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
   PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
   ```
3. **回放 WAL** —— SQLCipher 连 WAL 帧也是加密的。把原始帧直接写进明文库会损坏数据，
   必须交给 `sqlcipher3` 自己回放。
4. **解析消息体** —— 正文在 `40800` 字段，是 Protobuf（`MsgBody -> repeated MsgContent`），
   用 wire 级扫描提取。

## 数据布局

```
<账号目录>/nt_db/
  nt_msg.db          消息（c2c_msg_table / group_msg_table）
  profile_info.db    联系人（buddy_list / profile_info_v6）
  group_info.db      群与成员（group_list / group_member3）
```

账号目录有两种可能：

- 沙盒容器：`~/Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ/nt_qq_<md5>/`
- 非沙盒：`~/Library/Application Support/QQ/nt_qq_<md5>/`

多账号时请用 `--account-dir` 显式指定，工具**不会**自行猜测。

## 字段说明

列名是**数字字符串**（`"40050"`），SQL 中必须加双引号，
否则会被当成整数字面量。

| 字段 | 含义 |
|---|---|
| `40001` | 消息 ID |
| `40011` | 消息类型 |
| `40013` | 方向（0 = 收到，1/2 = 发送，3 = 系统） |
| `40027` | 会话分区键 |
| `40030` | c2c = 对方 QQ / group = 群号 |
| `40033` | 发送者 QQ |
| `40050` | 时间（Unix 秒） |
| `40800` | 消息体（Protobuf） |

注意 `40003` 与 `40850` 在 c2c 和 group 两张表里**语义不同**。

## JSON 输出

```json
{
  "chat": "示例群",
  "is_group": true,
  "count": 2,
  "messages": [
    {
      "msg_id": 1,
      "timestamp": 1791968733,
      "time": "2026-10-14 17:05:33",
      "sender_qq": 10001,
      "sender": "李老师",
      "direction": "received",
      "msg_type": "text",
      "text": "明天请带好写话本。",
      "parse_status": "ok"
    }
  ]
}
```

Protobuf 解析失败的消息会降级为 `"(unparsed)"` 并带 `"parse_status": "failed"`，
而**不会**中断整条命令。

## 已知限制

- **数据受登录来源限制** —— QQ 在新设备/新安装上只同步**近期一部分**历史。
  你所查询的账号可能只有部分记录，完整历史仍在原始安装的容器中。
- **仅支持 macOS** —— 密钥提取链路是 macOS 专属。
- **Protobuf 解析是启发式** —— 没有官方 schema。wire 级扫描覆盖文本、分享、
  图片与文件名；生僻消息类型可能降级。
- **不解码媒体** —— 图片、视频、语音仅给出文件名。

## 安全性

- **只读** —— 绝不写入 QQ 的数据库
- **纯本地** —— 全程无网络请求
- **密钥保护** —— `~/.qq-cli/` 权限 `0700`，密钥文件 `0600`，拒绝符号链接，
  写入为原子操作且先备份
- **缓存隔离** —— 解密后的库缓存在 `~/.cache/qq-cli/`，命名空间由
  「账号路径 + 密钥指纹」派生，权限 `0700`

## 免责声明

本项目为个人本地数据查看工具，不发送、不修改、不删除任何消息，
也不自动化 QQ 的任何功能。请仅在你拥有且当地法律允许的范围内使用。

## 许可

[Apache-2.0](LICENSE)
