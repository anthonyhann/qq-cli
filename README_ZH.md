<div align="center">

# 🐧 qq-cli

### 你的 QQ 聊天记录就在你硬盘上——像读数据一样读它，而不是靠截图。

一个 macOS 命令行工具：**只读**解密本地 QQ (NT) 数据库，输出稳定 JSON——11 个命令、2 个依赖、0 次网络请求。为 AI agent 设计：不抓界面、不上云，消息永远不离开这台机器。

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10-3776ab.svg?style=flat-square)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg?style=flat-square)](#-什么时候别用它)
[![Access](https://img.shields.io/badge/访问方式-只读-success.svg?style=flat-square)](#-隐私与安全)
[![Commands](https://img.shields.io/badge/命令-11-green.svg?style=flat-square)](#-核心能力)
[![Network](https://img.shields.io/badge/网络请求-0-brightgreen.svg?style=flat-square)](#-隐私与安全)

[快速开始](#-快速开始) · [命令一览](#-核心能力) · [工作原理](#-工作原理) · [隐私与安全](#-隐私与安全) · [English](README.md)

</div>

## 聊天记录是你的——但你读不到

- QQ NT 把聊天记录存在 SQLCipher 加密的 SQLite 里，官方没有本地 API。
- "导出到云端"的工具，要先让你的消息经过*别人的*服务器。
- 你的 AI agent 什么都能总结——唯独读不到你的收件箱。

qq-cli 在本机补上这一环：本地解密、JSON 查询、管道给你信任的任何东西。

```json
{
  "chat": "示例群",
  "is_group": true,
  "count": 2,
  "messages": [
    { "time": "2026-10-14 17:05:33", "sender": "李老师",
      "direction": "received", "msg_type": "text",
      "text": "明天请带练习册。", "parse_status": "ok" }
  ]
}
```

> 所有命令默认输出 JSON（给人看加 `--format text`）。单条消息 Protobuf 解析失败时降级为 `"(unparsed)"` + `parse_status: "failed"`——不会为了一条坏数据中断整个命令。

## ✨ 核心能力

| 命令 | 你得到 |
|---|---|
| `sessions` | 最近会话——私聊 + 群聊按时间合并 |
| `history` | 指定会话的聊天记录（时间范围、分页） |
| `search` | 跨会话全文搜索 |
| `new-messages` | 增量拉取（持久化检查点）——首次调用建基线，之后只返回增量 |
| `unread` | 有新消息的会话 |
| `groups` / `members` | 群列表（含成员数）/ 群成员（QQ号、昵称、群名片、角色） |
| `contacts` | 好友列表与资料查询 |
| `export-media` | 从本地媒体缓存导出图片/文件，附诚实的 `missing` 缺失清单 |
| `keys` / `init` | 密钥管理与校验 / 定位账号目录并导入密钥 |

## 🚀 快速开始

**1. 安装**（必须 Python 3.10——`sqlcipher3` 只有 cp310 预编译 wheel）：

```bash
uv venv --python 3.10 ~/.qq-cli-venv
uv pip install --python ~/.qq-cli-venv/bin/python git+https://github.com/anthonyhann/qq-cli.git
ln -sfn ~/.qq-cli-venv/bin/qq-cli ~/.local/bin/qq-cli
```

**2. 提取密钥并初始化**——16 字节密钥在 QQ 进程内存里；在一份**副本**上提取，已安装的 QQ 不会被改动：

```bash
cp -R /Applications/QQ.app /tmp/qqrun/QQ.app && open /tmp/qqrun/QQ.app
PID=$(pgrep -f 'qqrun/QQ.app/Contents/MacOS/QQ$')
lldb -p "$PID" --one-line "command script import $PWD/scripts/extract_key.py"
qq-cli init --keys ~/all_keys.json && qq-cli keys verify
```

**3. 查询：**

```bash
qq-cli sessions --limit 10
qq-cli history "群名称" --limit 20
qq-cli new-messages        # 增量：只返回上次之后的新消息
```

**给 AI Agent 的口令**——直接粘贴给你的 agent：

> 把 https://github.com/anthonyhann/qq-cli 安装进一个 Python 3.10 venv，按它 README 的步骤带我完成密钥提取，运行 `qq-cli init`，然后展示我最近的 10 个会话。

## 🔍 工作原理

QQ NT 的数据库不是普通 SQLite——磁盘布局是一个伪装头 `"SQLite header 3"` + **1024 字节 NT 元数据块**，之后才是 **SQLCipher 4** 页（`(文件大小 − 1024) % 4096 == 0`，已在 `nt_msg.db`、`group_info.db`、`profile_info.db` 及其 WAL 上验证）。处理管线：

1. **拷贝**账号容器里的数据库——原库从不以可写方式打开。
2. **剥掉** 1024 字节头部，用 SQLCipher 4 **解密**（`kdf_iter = 4000`，HMAC_SHA1 / PBKDF2_HMAC_SHA512——PRAGMA 顺序不能错）。
3. **回放 WAL**——必须交给 `sqlcipher3` 处理，直接拷贝裸帧会损坏明文库。
4. **解析消息体**——内容在 Protobuf `40800` 字段，用 wire-level 扫描器解（官方从未公开 schema）。

解密后的明文缓存位于 `~/.cache/qq-cli/`（`0700`），按账号路径 + 密钥指纹隔离命名。完整字段表（`40001` = 消息 ID、`40050` = 时间戳……）见 `qq_cli/core/` 源码注释。

## 🔐 隐私与安全

以下表述均可在代码中验证，不是宣传语：

- **零网络请求**——欢迎 grep 整个 `qq_cli/`：没有 `requests`、没有 `urllib`、没有 socket。一处都没有。
- **构造级只读**——源数据库先被拷贝、再解密到本地缓存，查询全是 SELECT。它不能发送、修改或删除任何消息。
- **密钥卫生**——`~/.qq-cli/` 权限 `0700`，密钥文件 `0600`，拒绝符号链接，写入原子化并带备份。
- **你的机器，你的责任**——只用于你自己的数据，并遵守当地法律。另见 [SECURITY.md](SECURITY.md)。

## 📁 目录结构

```text
qq-cli/
├── qq_cli/
│   ├── core/        # sqlcipher · db_cache · key_utils · messages · proto 解析 · media
│   ├── commands/    # 11 个子命令
│   └── output/      # JSON / 文本格式化
├── scripts/         # extract_key.py（lldb）· extract_key.exp（expect）· regdump.py
├── tests/           # smoke + media 测试
└── SECURITY.md · CONTRIBUTING.md
```

## ⚠️ 什么时候别用它

- **你用 Windows/Linux。** 密钥提取路径是 macOS 专属（lldb + hardened runtime 绕行）。
- **你要导出从没在 QQ 里点开过的媒体。** 未打开的附件只有服务端 `fileid` 句柄，直接请求返回 `retcode -5103009`（需要只有客户端能生成的签名）。`export-media` 是尽力而为，且必定打印 `missing` 清单，绝不藏缺。
- **你期待完整历史。** QQ 只向每个安装同步最近一段时间的记录——你查的账号可能只有部分历史。
- **你想自动化 QQ。** 这是个人本地数据查看工具：不发消息、不做机器人、不操控界面。

## 🙋 为什么做它

我想让自己的 agent 能回答"那个群里我又错过了什么"，而不必把多年聊天记录送进别人的云。唯一可接受的架构是：在我机器上解密、输出 JSON、永不外联。这就是全部设计。

⭐ 如果它把你的聊天记录从截图工作流里救了出来，一个 star 告诉我有人需要它。

## License

[Apache-2.0](LICENSE) © 2026 anthonyhann
