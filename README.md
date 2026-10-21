<div align="center">

# 🐧 qq-cli

### Your QQ chat history is on your disk. Read it like data, not like a screenshot.

A macOS CLI that decrypts local QQ (NT) databases **read-only** and answers in stable JSON — 11 commands, 2 dependencies, 0 network requests. Built so AI agents can query your chats without scraping the UI, and without your messages ever leaving the machine.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10-3776ab.svg?style=flat-square)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg?style=flat-square)](#-when-not-to-use-it)
[![Access](https://img.shields.io/badge/access-read--only-success.svg?style=flat-square)](#-privacy--security)
[![Commands](https://img.shields.io/badge/commands-11-green.svg?style=flat-square)](#-what-it-does)
[![Network](https://img.shields.io/badge/network_requests-0-brightgreen.svg?style=flat-square)](#-privacy--security)

[Quickstart](#-quickstart) · [Commands](#-what-it-does) · [How it works](#-how-it-works) · [Privacy](#-privacy--security) · [中文](README_zh.md)

</div>

## Your chats are yours — but unreadable

- QQ NT stores your history in a SQLCipher-encrypted SQLite file. There is no official local API.
- "Export to cloud" tools want your messages on *their* server first.
- Your AI agent can summarize your inbox — except it can't read it.

qq-cli closes that gap on-machine: decrypt locally, query as JSON, pipe to whatever you trust.

```json
{
  "chat": "Example group",
  "is_group": true,
  "count": 2,
  "messages": [
    { "time": "2026-10-14 17:05:33", "sender": "Teacher Li",
      "direction": "received", "msg_type": "text",
      "text": "Please bring the workbook tomorrow.", "parse_status": "ok" }
  ]
}
```

> Every command prints JSON by default (`--format text` for humans). Messages that fail Protobuf parsing degrade to `"(unparsed)"` with `parse_status: "failed"` — the command never aborts on one bad row.

## ✨ What it does

| Command | You get |
|---|---|
| `sessions` | Recent conversations — direct + group, merged by time |
| `history` | Chat history for one conversation (time range, pagination) |
| `search` | Full-text search across conversations |
| `new-messages` | Incremental fetch with persistent checkpoint — first call is the baseline, later calls return only the delta |
| `unread` | Conversations with new messages |
| `groups` / `members` | Group list with member counts / group roster (QQ, nickname, card, role) |
| `contacts` | Friends list and profile lookup |
| `export-media` | Export images/files from the local media cache, with an honest `missing` list |
| `keys` / `init` | Key management & verification / locate account directory and import keys |

## 🚀 Quickstart

**1. Install** (Python 3.10 exactly — `sqlcipher3` ships prebuilt wheels for cp310 only):

```bash
uv venv --python 3.10 ~/.qq-cli-venv
uv pip install --python ~/.qq-cli-venv/bin/python git+https://github.com/anthonyhann/qq-cli.git
ln -sfn ~/.qq-cli-venv/bin/qq-cli ~/.local/bin/qq-cli
```

**2. Get the key & init** — the 16-byte key lives in QQ's process memory; extract it from a *copy* of the app (the installed QQ is never modified):

```bash
cp -R /Applications/QQ.app /tmp/qqrun/QQ.app && open /tmp/qqrun/QQ.app
PID=$(pgrep -f 'qqrun/QQ.app/Contents/MacOS/QQ$')
lldb -p "$PID" --one-line "command script import $PWD/scripts/extract_key.py"
qq-cli init --keys ~/all_keys.json && qq-cli keys verify
```

**3. Query:**

```bash
qq-cli sessions --limit 10
qq-cli history "Group name" --limit 20
qq-cli new-messages        # incremental: only what arrived since last call
```

**For AI Agents** — paste this to your agent:

> Install https://github.com/anthonyhann/qq-cli into a Python 3.10 venv, walk me through the key-extraction steps in its README, run `qq-cli init`, then show my 10 most recent sessions.

## 🔍 How it works

QQ NT databases are not plain SQLite — the on-disk layout is a decoy `"SQLite header 3"` plus a **1024-byte NT metadata block**, then **SQLCipher 4** pages (`(filesize − 1024) % 4096 == 0`, verified across `nt_msg.db`, `group_info.db`, `profile_info.db` and their WALs). The pipeline:

1. **Copy** the databases out of the account container — the originals are never opened for writing.
2. **Strip** the 1024-byte header, **decrypt** with SQLCipher 4 (`kdf_iter = 4000`, HMAC_SHA1 / PBKDF2_HMAC_SHA512 — PRAGMA order matters).
3. **Replay the WAL** through `sqlcipher3` — raw frame copying would corrupt the plaintext.
4. **Parse message bodies** from Protobuf field `40800` with a wire-level scanner (no official schema exists).

Decrypted plaintext caches live under `~/.cache/qq-cli/` (`0700`), namespaced by account path + key fingerprint. Full layout & field reference (`40001` = msg id, `40050` = timestamp, …): see [README details](README_zh.md) and `qq_cli/core/`.

## 🔐 Privacy & security

Verified against the code, not just promised:

- **Zero network requests** — grep the imports: no `requests`, no `urllib`, no sockets. Anywhere.
- **Read-only by construction** — source databases are copied, then decrypted into a local cache; queries are SELECTs. It cannot send, modify, or delete messages.
- **Key hygiene** — `~/.qq-cli/` is `0700`, the key file is `0600`, symlinks refused, writes atomic with backup.
- **Your machine, your rules** — use it only on data you own, where local law permits. See [SECURITY.md](SECURITY.md).

## 📁 Repository layout

```text
qq-cli/
├── qq_cli/
│   ├── core/        # sqlcipher · db_cache · key_utils · messages · proto parser · media
│   ├── commands/    # the 11 subcommands
│   └── output/      # JSON / text formatter
├── scripts/         # extract_key.py (lldb) · extract_key.exp (expect) · regdump.py
├── tests/           # smoke + media tests
└── SECURITY.md · CONTRIBUTING.md
```

## ⚠️ When NOT to use it

- **You're on Windows/Linux.** Key extraction is macOS-specific (lldb + hardened-runtime workaround).
- **You need media you never opened in QQ.** Unopened attachments exist only as server-side `fileid` handles; fetching them returns `retcode -5103009` (needs a client-only signature). `export-media` is best-effort and always prints the `missing` list instead of hiding gaps.
- **You expect your full history.** QQ syncs only a recent slice to each install — the account you query may hold partial records.
- **You want to automate QQ.** This is a personal, local inspection tool: no sending, no bots, no UI automation.

## 🙋 Why it exists

I wanted my own agent to answer "what did I miss in that group?" without shipping years of chats to someone's cloud. The only acceptable architecture was: decrypt on my machine, output JSON, never dial out. That's the whole design.

⭐ If it saved your chat history from a screenshot workflow, a star tells me others want the same.

## License

[Apache-2.0](LICENSE) © 2026 anthonyhann
