"""媒体附件解析与导出。

QQ NT 的媒体文件**没有本地路径注册表**（rich_media.db 的 file_table 在
实测版本中为空，files_in_chat.db 无表），所以只能靠 MD5 扫描 nt_data 目录。

映射规则（实测验证）:
    消息声明  "836381B884681BA6718014448FD25A39.png"   ← 大写
    本地文件  836381b884681ba6718014448fd25a39_0.png   ← 小写 + 档位后缀

本地缓存目录:
    <account>/nt_data/Pic/YYYY-MM/Thumb/<md5>_<spec>.png
        spec=0   原图（优先）
        spec=720 缩略图

**能力边界（重要）**: 只有用户在 QQ 客户端中查看/下载过的媒体才会落盘。
未查看的附件仅有服务端 fileid 句柄，直接 HTTP 请求会返回
retcode -5103009（需要客户端生成的签名头），无法绕过客户端下载。
因此导出**无法保证完整性**，缺失项必须在报告中明确列出。
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from .proto import _to_text, _walk

# ---- 消息 blob 中的附件字段（实测确认）----

F_ATTACH_NAME = 45402      # 文件名（如 xxx.png / xxx.pdf）
F_ATTACH_URL_198 = 45802   # 下载地址（小图档）
F_ATTACH_URL_720 = 45803   # 下载地址（中图档）
F_ATTACH_URL_ORI = 45804   # 下载地址（原图档）

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_VOICE_EXT = {".amr", ".silk", ".mp3", ".m4a", ".wav"}
_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".txt", ".zip", ".rar", ".7z"}

_MD5_NAME_RE = re.compile(r"^([0-9a-fA-F]{32})[.](\w+)$")
_LOCAL_RE = re.compile(r"^([0-9a-f]{32})(?:_(\d+))?[.](\w+)$", re.IGNORECASE)

_SPEC_RANK = {"0": 0, "": 1, "720": 2}


@dataclass
class Attachment:
    """消息中声明的一个附件。"""
    filename: str = ""
    md5: str = ""
    ext: str = ""
    kind: str = "file"
    fileids: list = field(default_factory=list)
    message_id: int = 0
    timestamp: int = 0
    sender: str = ""
    is_group: bool = False
    peer: object = None

    @property
    def time_str(self):
        if not self.timestamp:
            return ""
        return datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        return {
            "filename": self.filename,
            "md5": self.md5,
            "kind": self.kind,
            "message_id": self.message_id,
            "time": self.time_str,
            "sender": self.sender,
            "is_group": self.is_group,
        }


def classify_ext(ext):
    e = "." + (ext or "").lower().lstrip(".")
    if e in _IMAGE_EXT:
        return "image"
    if e in _VIDEO_EXT:
        return "video"
    if e in _VOICE_EXT:
        return "voice"
    if e in _DOC_EXT:
        return "doc"
    return "file"


def extract_attachments(blob, *, message_id=0, timestamp=0, sender="",
                        is_group=False, peer=None):
    """从 40800 blob 提取附件声明。只返回带文件名的条目。"""
    if not blob:
        return []
    if isinstance(blob, str):
        blob = blob.encode("utf-8", errors="ignore")
    try:
        fields = []
        _walk(blob, 0, fields, max_depth=10)
    except Exception:  # noqa: BLE001
        return []

    names, fileids = [], []
    for f, chunk in fields:
        s = _to_text(chunk)
        if not s:
            continue
        if f == F_ATTACH_NAME:
            names.append(s.strip())
        elif f in (F_ATTACH_URL_198, F_ATTACH_URL_720, F_ATTACH_URL_ORI):
            m = re.search(r"fileid=([A-Za-z0-9_-]+)", s)
            if m:
                fileids.append(m.group(1))

    out = []
    for raw in names:
        base = os.path.basename(raw.strip())
        if not base:
            continue
        m = _MD5_NAME_RE.match(base)
        md5 = m.group(1).lower() if m else ""
        ext = (m.group(2) if m else os.path.splitext(base)[1].lstrip(".")).lower()
        out.append(Attachment(
            filename=base, md5=md5, ext=ext, kind=classify_ext(ext),
            fileids=list(dict.fromkeys(fileids)),
            message_id=message_id, timestamp=timestamp, sender=sender,
            is_group=is_group, peer=peer,
        ))
    return out


class MediaIndex:
    """扫描 nt_data 目录，建立 md5 -> 最优本地路径 的索引。"""

    SCAN_SUBDIRS = ("Pic", "Video", "dataline", "Emoji")

    def __init__(self, account_dir):
        self.account_dir = account_dir
        self._by_md5 = {}
        self._all = []
        self._built = False

    def build(self, force=False):
        if self._built and not force:
            return self
        self._by_md5.clear()
        self._all.clear()
        root = os.path.join(self.account_dir, "nt_data")
        if os.path.isdir(root):
            for sub in self.SCAN_SUBDIRS:
                d = os.path.join(root, sub)
                if os.path.isdir(d):
                    self._scan_dir(d)
        self._built = True
        return self

    def _scan_dir(self, d):
        for dirpath, _dirnames, filenames in os.walk(d):
            for name in filenames:
                m = _LOCAL_RE.match(name)
                if not m:
                    continue
                md5 = m.group(1).lower()
                spec = m.group(2) or ""
                path = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                rank = _SPEC_RANK.get(spec, 3)
                self._all.append((md5, spec, path, size))
                cur = self._by_md5.get(md5)
                if cur is None or rank < cur[0]:
                    self._by_md5[md5] = (rank, path, size)

    def find(self, md5):
        if not md5:
            return None
        self.build()
        got = self._by_md5.get(md5.lower())
        return got[1] if got else None

    def info(self, md5):
        self.build()
        got = self._by_md5.get((md5 or "").lower())
        if not got:
            return None
        return {"path": got[1], "size": got[2]}

    def known_md5s(self):
        self.build()
        return set(self._by_md5)

    def stats(self):
        self.build()
        return {"files": len(self._all), "unique_md5": len(self._by_md5)}


def safe_name(s, maxlen=24):
    """把任意字符串压成安全的文件名片段。"""
    if not s:
        return "unknown"
    s = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff.-]+", "_", str(s))
    s = s.strip("._-")
    if len(s) > maxlen:
        s = s[:maxlen]
    return s or "unknown"


# 文件头魔数 -> 真实扩展名（消息声明的扩展名不可靠，实测 .mp4 实为 JPEG）
_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),          # 需进一步看 WEBP 标记，够用
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),
    (b"\xd0\xcf\x11\xe0", "doc"),
    (b"\x1aE\xdf\xa3", "mkv"),  # EBML (mkv/webm)
    (b"\x00\x00\x00\x18ftyp", "mp4"),
    (b"\x00\x00\x00\x20ftyp", "mp4"),
    (b"#!AMR", "amr"),
]


def sniff_ext(path):
    """读取文件头判断真实扩展名；无法判断返回 None。

    消息里声明的扩展名可能是错的 —— 实测有 .mp4 实为 JPEG 的情况。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            if magic == b"RIFF" and b"WEBP" not in head:
                continue
            return ext
    return None


def build_export_name(att, seq, real_ext=None):
    """生成 001-1014-1640-发送者-md5前8.ext 形式的文件名。"""
    stamp = ""
    if att.timestamp:
        stamp = datetime.fromtimestamp(att.timestamp).strftime("%m%d-%H%M")
    who = safe_name(att.sender or "", 12)
    ident = (att.md5 or "").lower()[:8] or "nohash"
    parts = [f"{seq:03d}"]
    if stamp:
        parts.append(stamp)
    if who:
        parts.append(who)
    parts.append(ident)
    ext = (real_ext or att.ext or "bin").lower()
    return "-".join(parts) + "." + ext


def collect_attachments(app, *, chat=None, is_group=None, start_ts=None,
                        end_ts=None, kinds=None):
    """收集指定范围内的所有附件声明（去重）。"""
    import sqlite3

    from . import tables as T

    conn = sqlite3.connect(app.msg_db)
    peers = []
    if chat is not None:
        g = app.resolve_group(chat)
        if g:
            peers = [g["group_id"]]
            is_group = True
        else:
            q = app.resolve_contact(chat)
            if q is None:
                raise ValueError(f"找不到会话: {chat}")
            peers = [q]
            is_group = False

    out, scanned = [], 0
    tables = []
    if is_group in (None, True):
        tables.append((T.GROUP_TABLE, True))
    if is_group in (None, False):
        tables.append((T.C2C_TABLE, False))

    for table, grp in tables:
        where, params = [], []
        if peers:
            ph = ",".join("?" * len(peers))
            where.append(f"{T.col(T.F_PEER)} IN ({ph})")
            params.extend(peers)
        if start_ts is not None:
            where.append(f"{T.col(T.F_TIME)} >= ?")
            params.append(start_ts)
        if end_ts is not None:
            where.append(f"{T.col(T.F_TIME)} <= ?")
            params.append(end_ts)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = (f"SELECT {T.col(T.F_MSG_ID)},{T.col(T.F_TIME)},"
               f"{T.col(T.F_SENDER)},{T.col(T.F_SENDER_NAME)},"
               f"{T.col(T.F_NICK)},{T.col(T.F_BODY)},{T.col(T.F_PEER)} "
               f"FROM {T.col(table)} {clause} ORDER BY {T.col(T.F_TIME)}")
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            continue
        for msg_id, ts, sender_qq, sname, nick, blob, peer in rows:
            scanned += 1
            who = ""
            if grp:
                who = (sname or "").strip() or (nick or "").strip()
            if not who and sender_qq:
                who = app.name_for(sender_qq)
            for att in extract_attachments(
                    blob, message_id=msg_id, timestamp=ts, sender=who,
                    is_group=grp, peer=peer):
                if kinds and att.kind not in kinds:
                    continue
                out.append(att)

    # 去重：同一附件可能被多条消息引用
    seen, uniq = set(), []
    for a in out:
        key = (a.md5 or a.filename, a.timestamp)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    return uniq, scanned


def export_media(app, *, out_dir, chat=None, is_group=None, start_ts=None,
                 end_ts=None, kinds=None, include_orphans=False, dry_run=False):
    """导出指定会话的媒体附件。

    返回 dict:
      exported : [{file, source, md5, kind, time, sender, size}]
      missing  : [{filename, md5, kind, time, sender, reason, hint}]
      orphans  : [{path, md5, size, reason}]
      stats    : {...}
    """
    if not app.msg_db:
        raise RuntimeError("无法解密 nt_msg.db")

    index = MediaIndex(app.account_dir).build()
    out_dir = os.path.abspath(out_dir)
    img_dir = os.path.join(out_dir, "images")
    file_dir = os.path.join(out_dir, "files")

    attachments, scanned = collect_attachments(
        app, chat=chat, is_group=is_group, start_ts=start_ts,
        end_ts=end_ts, kinds=kinds)

    exported, missing = [], []
    used, seq = set(), 0

    for att in attachments:
        local = index.find(att.md5) if att.md5 else None
        if not local:
            missing.append({
                **att.to_dict(),
                "reason": "not_in_local_cache",
                "hint": "在 QQ 客户端中打开该消息即可缓存到本地",
            })
            continue

        seq += 1
        # 消息声明的扩展名可能不可靠，按文件头纠正
        real_ext = sniff_ext(local)
        kind = classify_ext(real_ext) if real_ext else att.kind
        if real_ext and real_ext != att.ext:
            name = build_export_name(att, seq, real_ext=real_ext)
        else:
            name = build_export_name(att, seq)
        target_dir = (img_dir if kind in ("image", "video", "voice")
                      else file_dir)
        target = os.path.join(target_dir, name)

        # 重名规避
        n = 1
        stem, ext = os.path.splitext(target)
        while target in used or os.path.exists(target):
            target = f"{stem}_{n}{ext}"
            n += 1
        used.add(target)

        try:
            size = os.path.getsize(local)
        except OSError:
            size = 0

        if not dry_run:
            os.makedirs(target_dir, mode=0o755, exist_ok=True)
            shutil.copy2(local, target)

        rec = att.to_dict()
        rec["kind"] = kind                      # 用探测到的真实类型覆盖
        if real_ext:
            rec["real_ext"] = real_ext
            if real_ext != att.ext:
                rec["ext_corrected"] = f"{att.ext} -> {real_ext}"
        rec.update({
            "file": os.path.relpath(target, out_dir),
            "source": local,
            "size": size,
        })
        exported.append(rec)

    orphans = []
    if include_orphans:
        referenced = {a.md5 for a in attachments if a.md5}
        for md5 in sorted(index.known_md5s() - referenced):
            info = index.info(md5)
            if info:
                orphans.append({
                    "md5": md5,
                    "path": info["path"],
                    "size": info["size"],
                    "reason": "no_message_reference",
                })

    return {
        "out_dir": out_dir,
        "chat": chat,
        "exported": exported,
        "missing": missing,
        "orphans": orphans,
        "stats": {
            "messages_scanned": scanned,
            "attachments_declared": len(attachments),
            "exported": len(exported),
            "missing": len(missing),
            "index": index.stats(),
        },
    }


def render_index_md(result, *, title=None):
    """生成 index.md：附件按时间顺序内联。"""
    lines = []
    heading = title or (f"{result['chat']} — 媒体导出" if result.get("chat") else "媒体导出")
    lines.append(f"# {heading}")
    lines.append("")
    st = result["stats"]
    lines.append(f"- 扫描消息：{st['messages_scanned']} 条")
    lines.append(f"- 声明附件：{st['attachments_declared']} 个")
    lines.append(f"- **成功导出：{st['exported']} 个**")
    if st["missing"]:
        lines.append(f"- 未能导出：{st['missing']} 个（本地缓存中没有，需在 QQ 中查看）")
    lines.append("")

    if result["exported"]:
        lines.append("## 已导出")
        lines.append("")
        for item in result["exported"]:
            rel = item["file"]
            if item["kind"] == "image":
                lines.append(f"### {item['time']} · {item['sender']}")
                lines.append("")
                lines.append(f"![{item['filename']}]({rel})")
                lines.append("")
            else:
                lines.append(f"- **[{item['filename']}]({rel})** "
                             f"— {item['time']} · {item['sender']}")
        lines.append("")

    if result["missing"]:
        lines.append("## 未能导出（本地无缓存）")
        lines.append("")
        lines.append("| 时间 | 发送者 | 文件 | 说明 |")
        lines.append("|---|---|---|---|")
        for m in result["missing"]:
            lines.append(f"| {m['time']} | {m['sender']} | `{m['filename']}` | "
                         f"需在 QQ 中打开该消息 |")
        lines.append("")

    return "\n".join(lines)
