"""Dump all registers at the breakpoint so we can identify the real key pointer."""
import lldb
import struct

_PATHS = ["/Applications/QQ.app/Contents/Resources/app/wrapper.node",
          "/tmp/qqrun/QQ.app/Contents/Resources/app/wrapper.node"]

def _find_func_va(path):
    with open(path, "rb") as f:
        data = f.read()
    if struct.unpack(">I", data[:4])[0] == 0xCAFEBABE:
        narch = struct.unpack(">I", data[4:8])[0]
        arm64_off = None
        for i in range(narch):
            base = 8 + i * 20
            cputype = struct.unpack(">i", data[base:base+4])[0]
            offset = struct.unpack(">I", data[base+8:base+12])[0]
            if cputype == 0x0100000C:
                arm64_off = offset; break
        if arm64_off is None: return None
    elif struct.unpack("<II", data[:8]) == (0xFEEDFACF, 0x0100000C):
        arm64_off = 0
    else:
        return None
    sl = data[arm64_off:]
    ncmds = struct.unpack("<I", sl[16:20])[0]
    off = 32; text_vmaddr = text_fileoff = text_size = 0
    for _ in range(ncmds):
        cmd, csz = struct.unpack("<II", sl[off:off+8])
        if cmd == 0x19:
            nsects = struct.unpack("<I", sl[off+64:off+68])[0]
            s = off + 72
            for _ in range(nsects):
                sname = sl[s:s+16].rstrip(b"\x00").decode("ascii","replace")
                sgname = sl[s+16:s+32].rstrip(b"\x00").decode("ascii","replace")
                saddr, ssz = struct.unpack("<QQ", sl[s+32:s+48])
                sfoff = struct.unpack("<I", sl[s+48:s+52])[0]
                if sname == "__text" and sgname == "__TEXT":
                    text_vmaddr, text_fileoff, text_size = saddr, sfoff, ssz
                s += 80
        off += csz
    text = sl[text_fileoff:text_fileoff+text_size]
    n1 = b"nt_sqlite3_key_v2: db="
    n2 = b"nt_sqlite3_key_v2: no key"
    i1 = data.find(n1, arm64_off); i2 = data.find(n2, arm64_off)
    if i1 < 0 or i2 < 0: return None
    va1, va2 = i1 - arm64_off, i2 - arm64_off
    def find_add(buf, imm12):
        out = []
        for i in range(0, len(buf)-4, 4):
            ins = struct.unpack("<I", buf[i:i+4])[0]
            if (ins & 0xFFC00000) == 0x91000000 and ((ins >> 10) & 0xFFF) == imm12:
                out.append(i)
        return out
    for h1 in find_add(text, va1 & 0xFFF):
        for h2 in find_add(text, va2 & 0xFFF):
            if abs(h1-h2) < 4096:
                start = min(h1,h2)
                for back in range(0, min(start,2048), 4):
                    pos = start-back
                    if (struct.unpack("<I", text[pos:pos+4])[0] & 0xFF8003FF) == 0xD10003FF:
                        return text_vmaddr + pos
    return None


def _dump(frame, bp_loc, extra_args, internal_dict):
    process = frame.GetThread().GetProcess()
    err = lldb.SBError()
    print("\n========== REGISTER DUMP AT nt_sqlite3_key_v2 ==========")
    regs = {}
    for rn in ["x0","x1","x2","x3","x4","x5","x6","x7","x8"]:
        r = frame.FindRegister(rn)
        if r.IsValid():
            v = r.GetValueAsUnsigned()
            regs[rn] = v
            # try reading printable bytes from this pointer
            sample = ""
            try:
                mem = process.ReadMemory(v, 32, err)
                if err.Success() and mem:
                    printable = bytes(c for c in mem if 32 <= c < 127)
                    if len(printable) >= 8:
                        sample = repr(mem[:24])
            except Exception:
                pass
            print("  %-3s = 0x%-18x %s" % (rn, v, sample))
    # x1 and x2 are the likely ptr/len pair
    for ptr_reg, len_reg in [("x1","x2"), ("x2","x3"), ("x1","x3")]:
        try:
            ptr = regs.get(ptr_reg); ln = regs.get(len_reg)
            if ptr and ln and 1 <= ln <= 64:
                mem = process.ReadMemory(ptr, ln, err)
                if err.Success() and mem:
                    try: txt = mem.decode("ascii")
                    except Exception: txt = mem.hex()
                    print("  >>> candidate %s(ptr)/%s(len=%d): %r" % (ptr_reg, len_reg, ln, txt))
        except Exception:
            pass
    print("========== END DUMP ==========")
    process.Continue()
    return False


def arm(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    for i in range(target.GetNumModules()):
        mod = target.GetModuleAtIndex(i)
        if mod.GetFileSpec().GetFilename() != "wrapper.node":
            continue
        load = mod.GetObjectFileHeaderAddress().GetLoadAddress(target)
        path = mod.GetFileSpec().fullpath
        va = _find_func_va(path)
        if va is None:
            result.SetError("VA not found"); return
        bp = target.BreakpointCreateByAddress(load + va)
        bp.SetScriptCallbackFunction("regdump._dump")
        print("[regdump] armed at 0x%x (load 0x%x + va 0x%x)" % (load+va, load, va))
        print("[regdump] now continue, then log in")
        return
    result.SetError("wrapper.node not loaded")


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand("command script add -f regdump.arm regdump-arm")
    print("[regdump] loaded; use: regdump-arm then c")
