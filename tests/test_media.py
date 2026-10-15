"""媒体导出核心逻辑的单测（不依赖真实 QQ 数据）。"""

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qq_cli.core.media import (Attachment, MediaIndex, build_export_name,
                               classify_ext, extract_attachments, safe_name,
                               sniff_ext)


def _png(path, w=8, h=8):
    """写一个最小的合法 PNG 头。"""
    data = b"\x89PNG\r\n\x1a\n" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"
    with open(path, "wb") as f:
        f.write(data)
    return path


def _jpeg(path):
    with open(path, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    return path


# ---- 类型判定 ----

def test_classify_ext():
    assert classify_ext("png") == "image"
    assert classify_ext(".PNG") == "image"
    assert classify_ext("mp4") == "video"
    assert classify_ext("pdf") == "doc"
    assert classify_ext("amr") == "voice"
    assert classify_ext("xyz") == "file"
    assert classify_ext("") == "file"
    print("  test_classify_ext OK")


def test_sniff_ext():
    with tempfile.TemporaryDirectory() as d:
        p = _png(os.path.join(d, "a.bin"))
        assert sniff_ext(p) == "png"
        j = _jpeg(os.path.join(d, "b.mp4"))
        assert sniff_ext(j) == "jpg", "JPEG 内容即使声明 mp4 也应识别为 jpg"
        z = os.path.join(d, "c.dat")
        open(z, "wb").write(b"garbage data here")
        assert sniff_ext(z) is None
        assert sniff_ext(os.path.join(d, "missing")) is None
    print("  test_sniff_ext OK")


# ---- 文件名 ----

def test_safe_name():
    assert safe_name("数学-高老师") == "数学-高老师"
    assert safe_name("a/b:c*d") == "a_b_c_d"
    assert safe_name("") == "unknown"
    assert safe_name(None) == "unknown"
    assert safe_name("x" * 100) == "x" * 24
    print("  test_safe_name OK")


def test_build_export_name():
    a = Attachment(filename="AB.png", md5="abcdef0123456789", ext="png",
                   kind="image", timestamp=1791967235, sender="高老师")
    name = build_export_name(a, 3)
    assert name.startswith("003-"), name
    assert "abcdef01" in name, name
    assert name.endswith(".png"), name
    # 真实扩展名覆盖
    name2 = build_export_name(a, 3, real_ext="jpg")
    assert name2.endswith(".jpg"), name2
    print("  test_build_export_name OK")


# ---- 附件提取 ----

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(num, payload):
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def test_extract_attachments():
    # 构造含 45402 文件名 + 45802 fileid 的 blob
    fname = b"836381B884681BA6718014448FD25A39.png"
    url = b"/download?appid=1407&fileid=EhQxnPKl-KbF&spec=198"
    inner = _field(45402, fname) + _field(45802, url)
    blob = _field(40800, inner)

    atts = extract_attachments(blob, message_id=7, timestamp=100, sender="高老师")
    assert len(atts) == 1, atts
    a = atts[0]
    assert a.md5 == "836381b884681ba6718014448fd25a39"
    assert a.ext == "png"
    assert a.kind == "image"
    assert a.message_id == 7
    assert a.sender == "高老师"
    assert a.fileids == ["EhQxnPKl-KbF"]

    # 非 MD5 文件名（如 .doc）应记为空 md5
    inner2 = _field(45402, "学生餐费退费申请.doc".encode("utf-8"))
    atts2 = extract_attachments(_field(40800, inner2))
    assert len(atts2) == 1
    assert atts2[0].md5 == ""
    assert atts2[0].kind == "doc"

    # 空输入
    assert extract_attachments(None) == []
    assert extract_attachments(b"") == []
    assert extract_attachments(b"\x00\x01\x02") == []
    print("  test_extract_attachments OK")


# ---- 索引 ----

def test_media_index():
    with tempfile.TemporaryDirectory() as d:
        thumb = os.path.join(d, "nt_data", "Pic", "2026-10", "Thumb")
        os.makedirs(thumb)
        md5 = "a" * 32
        orig = _png(os.path.join(thumb, md5 + "_0.png"))
        small = _png(os.path.join(thumb, md5 + "_720.png"), 4, 4)
        other = "b" * 32
        _png(os.path.join(thumb, other + ".png"))

        idx = MediaIndex(d).build()
        # 同 MD5 应择优选择 _0（原图）
        assert idx.find(md5) == orig, idx.find(md5)
        assert idx.find(other) is not None
        assert idx.find("c" * 32) is None
        assert idx.find("") is None
        assert idx.find(None) is None

        st = idx.stats()
        assert st["files"] == 3, st
        assert st["unique_md5"] == 2, st
        assert md5 in idx.known_md5s()

        # 空目录不应报错
        empty = MediaIndex(os.path.join(d, "nope")).build()
        assert empty.stats()["files"] == 0
    print("  test_media_index OK")


if __name__ == "__main__":
    print("媒体模块单测:")
    test_classify_ext()
    test_sniff_ext()
    test_safe_name()
    test_build_export_name()
    test_extract_attachments()
    test_media_index()
    print()
    print("全部通过")
