# QQ CLI

> Query local QQ (NT) data from the command line — built for AI agent integration.

<p>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.10-3776ab.svg"></a>
  <a href="https://github.com/anthonyhann/qq-cli/releases"><img alt="Release" src="https://img.shields.io/github/v/release/anthonyhann/qq-cli?color=green"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-lightgrey.svg">
  <img alt="Read only" src="https://img.shields.io/badge/access-read--only-success.svg">
</p>

Chat history · sessions · groups · members · contacts · unread · incremental new messages

**[中文文档](README_ZH.md)**

---

## Why

QQ NT stores chat history in a **SQLCipher-encrypted SQLite** database on your own
machine — there is no official local API. QQ CLI decrypts it **read-only** and exposes it
as structured JSON, so agents and scripts can query it without scraping the UI.

- **Zero network access** — everything stays on your machine
- **Read-only** — never writes, sends, or deletes messages
- **Agent-first** — JSON output by default, stable field names

## Features

| Command | Description |
|---|---|
| `sessions` | Recent conversations (direct + group, merged by time) |
| `history` | Chat history for a conversation (time range, pagination) |
| `search` | Full-text search across conversations |
| `groups` | Group list with member counts |
| `members` | Group members (QQ, nickname, card, role) |
| `contacts` | Friends list and profile lookup |
| `unread` | Conversations with new messages |
| `new-messages` | Incremental new messages (persistent checkpoint) |
| `export-media` | Export images/files out of the local media cache |
| `keys` | Key management and verification |
| `init` | Locate account directory, import and validate keys |

## Requirements

- macOS (Apple Silicon or Intel)
- QQ NT desktop client, installed and logged in at least once
- **Python 3.10** — `sqlcipher3` ships prebuilt wheels for cp310 only

## Installation

```bash
# 1. Create a dedicated venv (3.10 required)
uv venv --python 3.10 ~/.qq-cli-venv

# 2. Install dependencies from public PyPI
export UV_INDEX_URL=https://pypi.org/simple/
uv pip install --python ~/.qq-cli-venv/bin/python click sqlcipher3

# 3. Install QQ CLI
uv pip install --python ~/.qq-cli-venv/bin/python git+https://github.com/anthonyhann/qq-cli.git

# 4. Put it on your PATH
ln -sfn ~/.qq-cli-venv/bin/qq-cli ~/.local/bin/qq-cli
```

> Behind a corporate mirror that lacks `sqlcipher3`? `--index-url https://pypi.org/simple/` is required.

## Quick start

### 1. Extract the database key

QQ's key is a **16-byte ASCII string** living in process memory. It is read from the
`x2` (pointer) / `x3` (length) registers of `nt_sqlite3_key_v2` at a debugger breakpoint.

Because the official QQ build runs with a hardened runtime, `lldb` cannot attach to it.
The safe approach is to **work on a copy** — the original app is never modified:

```bash
# Copy QQ and give it its own bundle id (isolated container)
cp -R /Applications/QQ.app /tmp/qqrun/QQ.app
plutil -replace CFBundleIdentifier -string com.tencent.qq.debugrun \
    /tmp/qqrun/QQ.app/Contents/Info.plist
codesign --force --deep --sign - /tmp/qqrun/QQ.app
open /tmp/qqrun/QQ.app
```

Then attach and arm the breakpoint:

```bash
PID=$(pgrep -f 'qqrun/QQ.app/Contents/MacOS/QQ$')
lldb -p "$PID" --one-line "command script import $PWD/scripts/extract_key.py"
#   (lldb) image list -o -f | grep wrapper.node   # confirm the module is loaded
#   (lldb) qq-arm                               # auto-computes the address
#   (lldb) c                                      # then click "Log in" in QQ
#   → the key is printed automatically
```

`scripts/regdump.py` dumps every register at the breakpoint, which is the reliable way to
confirm *which* registers hold the pointer and length on a given QQ version.

> **Warning:** signing with `--deep` rewrites the signatures of nested helper bundles
> (`QQ Helper.app`). Doing that to the *installed* app makes the GPU process crash on
> launch. Always work on a copy.

### 2. Initialize

```bash
qq-cli init --keys ~/all_keys.json
qq-cli keys verify
```

### 3. Query

```bash
qq-cli sessions --limit 10
qq-cli history "Group name" --limit 20
qq-cli search "keyword" --chat "Group name"
qq-cli members "Group name" --limit 20
qq-cli new-messages            # first call = baseline, later calls = delta
```

Every command accepts `--format json` (default) or `--format text`.

## How it works

QQ NT databases are **not** plain SQLite. The on-disk layout is:

```
bytes  0..15    "SQLite header 3\x00"   ← decoy header, NOT "SQLite format 3"
bytes 16..1023  NT metadata block
bytes 1024..    SQLCipher 4 pages
```

`(filesize - 1024) % 4096 == 0` — verified across `nt_msg.db`, `group_info.db`,
`profile_info.db`, and the WAL files.

The pipeline:

1. **Strip** the 1024-byte NT header
2. **Decrypt** with SQLCipher 4 — PRAGMA order matters:
   ```
   PRAGMA cipher_page_size = 4096;        -- must come before key
   PRAGMA key = '<16-byte ASCII>';
   PRAGMA kdf_iter = 4000;
   PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
   PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
   ```
3. **Replay the WAL** — SQLCipher encrypts WAL frames too. Writing raw frames into a
   plaintext database corrupts it; the WAL must be handed to `sqlcipher3` to replay.
4. **Parse message bodies** — content lives in the `40800` Protobuf field
   (`MsgBody -> repeated MsgContent`), decoded with a wire-level scanner.

## Data layout

```
<account-dir>/nt_db/
  nt_msg.db          messages (c2c_msg_table / group_msg_table)
  profile_info.db    contacts (buddy_list / profile_info_v6)
  group_info.db      groups and members (group_list / group_member3)
```

The account directory is either:

- Sandboxed: `~/Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ/nt_qq_<md5>/`
- Non-sandboxed: `~/Library/Application Support/QQ/nt_qq_<md5>/`

With multiple accounts, specify one explicitly via `--account-dir`; the tool never guesses.

## Field reference

Column names are **numeric strings** (`"40050"`) and must be double-quoted in SQL,
otherwise SQLite treats them as integer literals.

| Field | Meaning |
|---|---|
| `40001` | Message ID |
| `40011` | Message type |
| `40013` | Direction (0 = received, 1/2 = sent, 3 = system) |
| `40027` | Conversation partition key |
| `40030` | c2c = peer QQ / group = group number |
| `40033` | Sender QQ |
| `40050` | Timestamp (Unix seconds) |
| `40800` | Message body (Protobuf) |

Note that `40003` and `40850` have **different meanings** between the c2c and group tables.

## JSON output

```json
{
  "chat": "Example group",
  "is_group": true,
  "count": 2,
  "messages": [
    {
      "msg_id": 1,
      "timestamp": 1791968733,
      "time": "2026-10-14 17:05:33",
      "sender_qq": 10001,
      "sender": "Teacher Li",
      "direction": "received",
      "msg_type": "text",
      "text": "Please bring the workbook tomorrow.",
      "parse_status": "ok"
    }
  ]
}
```

Messages that fail Protobuf parsing degrade to `"(unparsed)"` with
`"parse_status": "failed"` instead of aborting the command.

## Exporting media

```bash
qq-cli export-media "Group name" --out ./export
qq-cli export-media "Group name" --out ./export --report     # report only, copy nothing
qq-cli export-media 648974225 --start-time 2026-10-14 --out ./export
qq-cli export-media "Group name" --out ./export --kind image --kind doc
qq-cli export-media "Group name" --out ./export --orphans    # also list unreferenced files
```

Output layout:

```
export/
  images/001-1014-1640-TeacherLi-836381b8.png
  files/002-1014-1705-TeacherZhou-worksheet.pdf
  index.md             attachments inlined in chronological order
  export-report.json   full metadata + the missing list
```

**Read this before relying on it.** QQ only caches media you have actually opened in the
client. Unopened attachments exist solely as a server-side `fileid` handle, and fetching
them over HTTP returns `retcode -5103009` because the request needs a signature that only
the QQ client can produce. There is no way around this from outside the client.

So the export is **best-effort by design**. The command never hides a gap: everything it
could not export is listed under `missing`, with sender and timestamp, so you know exactly
which messages to open in QQ before re-running.

Two details worth knowing:

- There is **no local path registry** (`rich_media.db`'s `file_table` is empty in the builds
  tested), so files are located by scanning `nt_data/` and matching the **MD5** declared in
  the message — uppercase in the message, lowercase on disk.
- The **declared extension is not trustworthy**. Files announced as `.mp4` turned out to be
  JPEG. The exporter sniffs the file header and corrects both the extension and the reported
  kind, recording the change as `ext_corrected` in the report.

## Limitations


- **Location-scoped data** — QQ only syncs a recent slice of history to a new device or
  install. The account you query may hold partial history; the full record stays in the
  original installation's container.
- **macOS only** — the key extraction path is macOS-specific.
- **Protobuf parsing is heuristic** — there is no official schema. Wire-level scanning
  covers text, shares, images, and file names; exotic message types may degrade.
- **Media is not decoded** — images, video, and voice messages are reported by name only.

## Security

- **Read-only** — the tool never writes to QQ's databases
- **Local only** — no network requests at any point
- **Key hygiene** — `~/.qq-cli/` is `0700`, the key file is `0600`, symlinks are refused,
  writes are atomic with backup
- **Isolated cache** — decrypted databases are cached under `~/.cache/qq-cli/<` namespace
  derived from account path + key fingerprint, `0700`

## Disclaimer

This is a personal, local data-inspection tool. It does not send, modify, or delete
messages, and it does not automate any QQ functionality. Use it only on data you own and
only where permitted by local law.

## License

[Apache-2.0](LICENSE)
