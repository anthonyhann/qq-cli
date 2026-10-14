"""QQ 消息体 Protobuf 解析 —— 字段 40800 (MsgBody -> repeated MsgContent)。

没有 .proto 定义可依赖，这里做「wire 级扫描 + 文本启发式」：
  1. 逐字段解析 varint / length-delimited，收集所有嵌套层级的字符串
  2. 过滤掉协议内部标记（xml 命名空间、cdn 域名、base64 长串等）
  3. 输出可读正文

设计原则：**解析失败不抛异常**，降级为占位文本并保留原始 bytes。
"""

import re

# 协议噪音：这些字符串是消息体的元数据，不是用户可见正文
_NOISE_PATTERNS = [
    re.compile(r"^https?://"),
    re.compile(r"^//"),
    re.compile(r"^[A-Za-z0-9_\-]{20,}$"),          # base64/token 长串
    re.compile(r"^\{[A-Za-z0-9_\-]{8,}\}$"),
    re.compile(r"^[0-9a-fA-F]{16,}$"),               # hex 摘要
    re.compile(r"^com\.[a-z0-9.]+$"),
    re.compile(r"^[a-z]+\.[a-z]+\.[a-z.]+$"),       # 命名空间
    re.compile(r"^\d{6,}$"),                         # 纯数字 id
]
_NOISE_EXACT = {
    "qqconnect.sdkshare", "bizsrc", "config", "ctime", "forward", "token",
    "xml", "json", "utf-8", "UTF-8", "md5", "sha1", "image", "video",
    "record", "file", "ptt", "pic", "face", "markdown", "com.tencent.tuwen.lua",
    "qzone", "photo", "app", "news", "mqqapi", "mqqapiwtlogin", "mozilla",
    "android", "iphone", "windows", "mac", "pc",
}


def _read_varint(buf, i):
    shift = 0
    val = 0
    while i < len(buf):
        b = buf[i]
        val |= (b & 0x7F) << shift
        i += 1
        if not (b & 0x80):
            return val, i
        shift += 7
        if shift > 63:
            return None, i
    return None, i


def _walk(buf, depth, out, max_depth=8):
    """递归收集所有 length-delimited 字段的原始 bytes。"""
    if depth > max_depth:
        return
    i = 0
    n = len(buf)
    while i < n:
        try:
            key, i = _read_varint(buf, i)
        except Exception:
            return
        if key is None:
            return
        field = key >> 3
        wire = key & 0x07
        if wire == 0:
            _, i = _read_varint(buf, i)
            if i > n:
                return
        elif wire == 2:
            ln, i = _read_varint(buf, i)
            if ln is None or i + ln > n:
                return
            chunk = buf[i:i + ln]
            i += ln
            out.append((field, chunk))
            _walk(chunk, depth + 1, out, max_depth)
        elif wire == 5:
            i += 4
        elif wire == 1:
            i += 8
        else:
            return


def _is_noise(s):
    if s in _NOISE_EXACT:
        return True
    if len(s) < 2:
        return True
    return any(p.match(s) for p in _NOISE_PATTERNS)


def _to_text(chunk):
    try:
        s = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not s:
        return None
    # 必须含可见字符且不是纯控制字符
    if not any(32 <= ord(c) and c.isprintable() for c in s):
        return None
    return s


_JSON_CARD = re.compile(r'^\s*\{.*"app"\s*:', re.S)
_JSON_TITLE = re.compile(r'"title"\s*:\s*"([^"]{2,120})"')


def _summarize_card(s):
    """分享卡片是 JSON，取 title 作为可读摘要。"""
    m = _JSON_TITLE.search(s)
    if m:
        return m.group(1)
    return None


def extract_text(blob, max_len=2000):
    """从 40800 blob 提取可读正文；失败返回 None。"""
    if not blob:
        return None
    if isinstance(blob, str):
        blob = blob.encode("utf-8", errors="ignore")
    try:
        fields = []
        _walk(blob, 0, fields, max_depth=8)
    except Exception:  # noqa: BLE001
        return None

    # 先收集所有候选字符串
    cands = []
    for _field, chunk in fields:
        s = _to_text(chunk)
        if not s or _is_noise(s):
            continue
        if _JSON_CARD.match(s):
            title = _summarize_card(s)
            if title:
                cands.append(f"[分享] {title}")
            continue
        cands.append(s)

    if not cands:
        # 退一步：直接在整块里找 UTF-8 中文/可读串
        s = _to_text(blob)
        if s:
            cands = [s]

    if not cands:
        return None

    # 去重保序，优先较长且含中文的
    seen, uniq = set(), []
    for s in cands:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)

    uniq.sort(key=lambda x: (0 if re.search(r"[\u4e00-\u9fff]", x) else 1, -len(x)))
    text = "\n".join(uniq)
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text or None
