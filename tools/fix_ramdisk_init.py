#!/usr/bin/env python3
"""Inject a static /init into a gzipped cpio ramdisk if it is missing.

Android's boot path is: bootloader -> kernel -> exec /init .
If /init is absent the kernel panics/reboots after the splash and the device
sits on the second boot screen forever.  The upstream build script deletes
the stock symlink (/init -> /system/bin/init) and replaces it with a custom
static wrapper, but the wrapper can silently fail to make it into the cpio,
so we verify and repair here.

Usage:
  fix_ramdisk_init.py <ramdisk.cpio.gz> <static_init_binary> [--append-xz FILE]

Rebuilds the gzip member content with /init present, preserving every other
entry byte-for-byte (name, mode, size, inode ordering by path).
"""
import sys
import os
import zlib
import gzip
import argparse


def parse_cpio(blob):
    """Return list of dicts describing each entry (raw preserved)."""
    entries = []
    i = 0
    while i + 110 <= len(blob):
        if blob[i:i + 6] not in (b"070701", b"070702"):
            break
        def h(o, k):
            return int(blob[i + o:i + o + k], 16)
        mode = h(14, 8)
        filesize = h(54, 8)
        namesize = h(94, 8)
        name = blob[i + 110:i + 110 + namesize - 1].decode("utf-8", "replace")
        hdr_end = (i + 110 + namesize + 3) & ~3
        body = blob[hdr_end:hdr_end + filesize]
        pad = ((filesize + 3) & ~3) - filesize
        raw = blob[i:hdr_end + filesize + pad]
        entries.append(dict(name=name, mode=mode, filesize=filesize,
                            body=body, raw=raw, hdr=blob[i:hdr_end]))
        i = hdr_end + ((filesize + 3) & ~3)
        if name == "TRAILER!!!":
            break
    return entries


def build_cpio(entries):
    out = bytearray()
    for e in entries:
        out += e["raw"]
    return bytes(out)


def make_entry(name, body, mode, ino):
    """Create a cpio newc entry."""
    namez = name.encode() + b"\x00"
    fields = [
        ino & 0xFFFFFFFF,          # ino
        mode,                      # mode
        0, 0,                      # uid, gid
        1,                         # nlink
        0,                         # mtime
        len(body),                 # filesize
        0, 0,                      # devmajor, devminor
        0, 0,                      # rdevmajor, rdevminor
        len(namez),                # namesize
        0,                         # check
    ]
    hdr = b"070701" + b"".join(b"%08X" % f for f in fields)
    # hdr 是 6 + 13*8 = 110 字节
    pad_name = (-(110 + len(namez))) % 4
    pad_body = (-len(body)) % 4
    return hdr + namez + b"\x00" * pad_name + body + b"\x00" * pad_body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ramdisk")
    ap.add_argument("init_binary")
    ap.add_argument("--append-xz", default=None,
                    help="optional xz blob to re-append after the gzip member")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_path = args.out or args.ramdisk
    raw = open(args.ramdisk, "rb").read()

    # --- split into gzip member(s) + trailing tail ---
    members = []
    pos = 0
    while pos < len(raw) and raw[pos:pos + 2] == b"\x1f\x8b":
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        dec = d.decompress(raw[pos:])
        consumed = len(raw) - pos - len(d.unused_data)
        members.append((raw[pos:pos + consumed], dec))
        pos += consumed
    tail = raw[pos:]

    if not members:
        print("ERROR: no gzip member found", file=sys.stderr)
        return 1

    gz_bytes, cpio = members[0]
    print(f"gzip member: {len(gz_bytes):,} compressed / {len(cpio):,} decompressed")
    print(f"tail after gzip: {len(tail):,} bytes")

    entries = parse_cpio(cpio)
    names = [e["name"] for e in entries]
    print(f"cpio entries: {len(entries)}")

    has_init = "init" in names
    print(f"'init' present: {has_init}")

    init_body = open(args.init_binary, "rb").read()
    elf_magic = b"\x7fELF"
    is_elf = init_body[:4] == elf_magic
    print("init binary: {:,} bytes  ELF={}".format(len(init_body), is_elf))

    changed = False

    if has_init:
        idx = names.index("init")
        cur = entries[idx]
        fmt = cur["mode"] & 0o170000
        if fmt == 0o100000 and cur["body"] == init_body:
            print("[i] /init already correct, nothing to do")
        else:
            kind = "SYMLINK" if fmt == 0o120000 else ("FILE" if fmt == 0o100000 else oct(fmt))
            print(f"[!] /init is {kind} -- replacing with static binary")
            entries[idx] = dict(
                name="init", mode=0o100750, filesize=len(init_body),
                body=init_body,
                raw=make_entry("init", init_body, 0o100750, idx + 1),
                hdr=None)
            changed = True
    else:
        print("[!] /init MISSING -- injecting at position 0")
        newent = dict(name="init", mode=0o100750, filesize=len(init_body),
                      body=init_body,
                      raw=make_entry("init", init_body, 0o100750, 1),
                      hdr=None)
        entries.insert(0, newent)
        changed = True

    if not changed:
        # still normalise tail if caller asked
        pass

    if changed:
        new_cpio = build_cpio(entries)
        new_gz = gzip.compress(new_cpio, 9, mtime=0)
        print(f"rebuilt: cpio {len(new_cpio):,} -> gzip {len(new_gz):,}")

        # verify
        chk = gzip.decompress(new_gz)
        chk_names = [e["name"] for e in parse_cpio(chk)]
        assert "init" in chk_names, "post-build verification failed: init missing"
        print(f"[ok] rebuilt cpio has {len(chk_names)} entries incl. init")

        out = new_gz + tail
        if args.append_xz:
            xz = open(args.append_xz, "rb").read()
            out += xz
            print(f"appended xz blob: {len(xz):,} bytes")

        open(out_path, "wb").write(out)
        print(f"[ok] wrote {out_path} ({len(out):,} bytes)")
    else:
        # ensure requested output exists
        if out_path != args.ramdisk:
            open(out_path, "wb").write(raw)
            print(f"[ok] copied to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
