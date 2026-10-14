#!/usr/bin/env python3
"""QQ NT 数据库密钥提取 —— lldb 自动化模块。

用法（两个终端）:

  终端 A:
    lldb -n QQ -w --one-line "command script import $PWD/scripts/extract_key.py"

  终端 B（等 lldb 出现 "Waiting for process" 后）:
    open /path/to/QQ.app

  回到终端 A:
    (lldb) qq-arm      # 自动定位 nt_sqlite3_key_v2 并下断点
    (lldb) c           # 继续运行
    → 在 QQ 界面点击「登录」，密钥自动打印

原理
----
QQ NT 的 wrapper.node 内部静态链接了 SQLCipher，通过 nt_sqlite3_key_v2
把密钥传给 SQLite。该函数在 QQ 首次打开数据库（即登录时）被调用，
此时密钥以明文存在于寄存器中：

    x0 = sqlite3* 句柄
    x1 = 诊断用字符串（非密钥，实测确认）
    x2 = 密钥指针
    x3 = 密钥长度（通常 16）

函数地址不是硬编码的：本脚本在 wrapper.node 中搜索两条诊断字符串
（"nt_sqlite3_key_v2: db=" 与 "nt_sqlite3_key_v2: no key"），
再回溯到包含它们的函数序言，因此**跨 QQ 版本可用**。

用 scripts/regdump.py 可以 dump 全部寄存器来核对这个约定。

注意
----
- 官方 QQ 启用 hardened runtime，lldb 无法 attach；需要在**副本**上操作。
- 用 --deep 重签名会破坏 QQ Helper.app 的签名，导致 GPU 进程崩溃。
  务必只在副本上做，不要动 /Applications/QQ.app。
"""

from __future__ import annotations

import os
import struct

import lldb

_MARK_DB = b"nt_sqlite3_key_v2: db="
_MARK_NOKEY = b"nt_sqlite3_key_v2: no key"

# login.db 使用一个全平台相同的固定密钥，它不是聊天记录的密钥，命中时跳过。
_LOGIN_DB_KEY = "BD156D6710D54D8782F4"

_va_cache: dict = {}


def _find_func_va(path):
    """在 wrapper.node 中定位 nt_sqlite3_key_v2 的 VA。返回 (va, err)。"""
    with open(path, "rb") as f:
        data = f.read()

    # 安装目录是 fat binary，热更新目录是单架构 arm64
    if struct.unpack(">I", data[:4])[0] == 0xCAFEBABE:
        narch = struct.unpack(">I", data[4:8])[0]
        arm64 = None
        for i in range(narch):
            base = 8 + i * 20
            cputype = struct.unpack(">i", data[base:base + 4])[0]
            offset = struct.unpack(">I", data[base + 8:base + 12])[0]
            if cputype == 0x0100000C:
                arm64 = offset
                break
        if arm64 is None:
            return None, "no arm64 slice"
    elif struct.unpack("<II", data[:8]) == (0xFEEDFACF, 0x0100000C):
        arm64 = 0
    else:
        return None, "not an arm64 Mach-O"

    sl = data[arm64:]
    ncmds = struct.unpack("<I", sl[16:20])[0]
    off, text_vmaddr, text_fileoff, text_size = 32, 0, 0, 0
    for _ in range(ncmds):
        cmd, csz = struct.unpack("<II", sl[off:off + 8])
        if cmd == 0x19:  # LC_SEGMENT_64
            nsects = struct.unpack("<I", sl[off + 64:off + 68])[0]
            s = off + 72
            for _ in range(nsects):
                sname = sl[s:s + 16].rstrip(b"\x00").decode("ascii", "replace")
                sgname = sl[s + 16:s + 32].rstrip(b"\x00").decode("ascii", "replace")
                saddr, ssz = struct.unpack("<QQ", sl[s + 32:s + 48])
                sfoff = struct.unpack("<I", sl[s + 48:s + 52])[0]
                if sname == "__text" and sgname == "__TEXT":
                    text_vmaddr, text_fileoff, text_size = saddr, sfoff, ssz
                s += 80
        off += csz

    text = sl[text_fileoff:text_fileoff + text_size]

    i1 = data.find(_MARK_DB, arm64)
    i2 = data.find(_MARK_NOKEY, arm64)
    if i1 < 0 or i2 < 0:
        return None, "diagnostic strings not found (incompatible wrapper.node?)"
    va1, va2 = i1 - arm64, i2 - arm64

    def find_add(buf, imm12):
        out = []
        for i in range(0, len(buf) - 4, 4):
            ins = struct.unpack("<I", buf[i:i + 4])[0]
            if (ins & 0xFFC00000) == 0x91000000 and ((ins >> 10) & 0xFFF) == imm12:
                out.append(i)
        return out

    for h1 in find_add(text, va1 & 0xFFF):
        for h2 in find_add(text, va2 & 0xFFF):
            if abs(h1 - h2) < 4096:
                start = min(h1, h2)
                for back in range(0, min(start, 2048), 4):
                    pos = start - back
                    # SUB sp, sp, #imm = 函数序言
                    if (struct.unpack("<I", text[pos:pos + 4])[0] & 0xFF8003FF) == 0xD10003FF:
                        return text_vmaddr + pos, None
    return None, "function entry not found"


def _va_for(path):
    if path not in _va_cache:
        _va_cache[path] = _find_func_va(path)
    return _va_cache[path]


def _on_breakpoint(frame, bp_loc, extra_args, internal_dict):
    """断点命中：读取 x2/x3，打印密钥。"""
    process = frame.GetThread().GetProcess()
    x2 = frame.FindRegister("x2")
    x3 = frame.FindRegister("x3")
    if not x2.IsValid() or not x3.IsValid():
        print("[qq-key] 无法读取 x2/x3")
        return False

    ptr = x2.GetValueAsUnsigned()
    length = x3.GetValueAsUnsigned()

    err = lldb.SBError()
    raw = process.ReadMemory(ptr, length, err)

    if err.Success() and raw:
        try:
            key = raw.decode("ascii")
        except UnicodeDecodeError:
            key = raw.hex()

        if key == _LOGIN_DB_KEY:
            print("[qq-key] 命中 login.db 固定密钥（非聊天库），跳过")
            process.Continue()
            return False

        print()
        print("=" * 60)
        print("  密钥提取成功")
        print(f"  KEY    : {key}")
        print(f"  LENGTH : {length}")
        print("=" * 60)
        print()
        print("  保存为 JSON 后运行: qq-cli init --keys <file>")
        print('  格式: { "nt_qq_<hash>/nt_db/nt_msg.db": { "enc_key": "<KEY>" } }')
        print()
        print("  或直接使用:")
        print(f"    python -c \"import json,sys;print(json.dumps(sys.argv[1]))\" \"{key}\"")
        print()
    else:
        print(f"[qq-key] 读取内存失败: {err}")

    process.Continue()
    return False


def qq_arm(debugger, command, result, internal_dict):
    """在当前已加载的 wrapper.node 上定位函数并下断点。"""
    target = debugger.GetSelectedTarget()
    for i in range(target.GetNumModules()):
        mod = target.GetModuleAtIndex(i)
        if mod.GetFileSpec().GetFilename() != "wrapper.node":
            continue

        load_addr = mod.GetObjectFileHeaderAddress().GetLoadAddress(target)
        if load_addr == lldb.LLDB_INVALID_ADDRESS:
            continue

        path = mod.GetFileSpec().fullpath
        va, err = _va_for(path)
        if va is None:
            result.SetError(f"[qq-key] 定位失败: {err}")
            return

        bp = target.BreakpointCreateByAddress(load_addr + va)
        if not bp.IsValid():
            result.SetError(f"[qq-key] 创建断点失败 @ 0x{load_addr + va:x}")
            return
        bp.SetScriptCallbackFunction("extract_key._on_breakpoint")

        print(f"[qq-key] wrapper.node : {path}")
        print(f"[qq-key] 加载地址      : 0x{load_addr:x}")
        print(f"[qq-key] 函数 VA       : 0x{va:x}")
        print(f"[qq-key] 断点          : 0x{load_addr + va:x}")
        print("[qq-key] 执行 c 继续，然后在 QQ 中点击「登录」")
        return

    result.SetError(
        "[qq-key] 未找到 wrapper.node 模块。先执行 process continue，"
        "等 QQ 界面出现后再试。")


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand("command script add -f extract_key.qq_arm qq-arm")
    print("[qq-key] 已加载。步骤:")
    print("[qq-key]   1. open <QQ.app>              # 另一个终端")
    print("[qq-key]   2. process continue           # 让 QQ 起来")
    print("[qq-key]   3. Ctrl-C                    # 暂停")
    print("[qq-key]   4. image list -o -f | grep wrapper.node   # 确认模块已加载")
    print("[qq-key]   5. qq-arm                    # 下断点")
    print("[qq-key]   6. c                         # 然后在 QQ 点击「登录」")
    print()
