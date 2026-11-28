#!/usr/bin/env python3
"""Check whether a gzipped cpio ramdisk has a usable /init.

Android boots via: bootloader -> kernel -> exec /init
A missing /init leaves the device stuck on the second boot splash.

Exit code 0 = /init present and usable (regular ELF file)
Exit code 1 = missing, or present as symlink/wrong type

Usage: check_ramdisk_init.py <ramdisk.cpio.gz> [--quiet]
"""
import sys
import zlib


def first_gzip_member(raw):
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw)
    return out


def find_entry(blob, target):
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
        if name == target:
            return mode, filesize, body
        i = hdr_end + ((filesize + 3) & ~3)
        if name == "TRAILER!!!":
            break
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    if len(args) != 1:
        print("usage: check_ramdisk_init.py <ramdisk.cpio.gz> [--quiet]", file=sys.stderr)
        return 2

    raw = open(args[0], "rb").read()
    if raw[:2] != b"\x1f\x8b":
        print(f"[x] not gzip (magic {raw[:2].hex()})", file=sys.stderr)
        return 1

    blob = first_gzip_member(raw)
    ent = find_entry(blob, "init")

    if ent is None:
        print("[x] /init NOT FOUND in ramdisk")
        return 1

    mode, size, body = ent
    fmt = mode & 0o170000
    if fmt == 0o120000:
        tgt = body.decode("utf-8", "replace")
        print(f"[!] /init is a SYMLINK -> {tgt!r}")
        # A symlink to /system/bin/init is what stock has, and it works when
        # the real init lives in the system image. For the custom debug
        # ramdisk we require a self-contained binary.
        return 1
    if fmt != 0o100000:
        print(f"[x] /init has unexpected type {oct(fmt)}")
        return 1

    is_elf = body[:4] == b"\x7fELF"
    if not is_elf:
        print(f"[x] /init is a regular file but not ELF (head {body[:8].hex()})")
        return 1

    if not quiet:
        print(f"[ok] /init present: regular ELF, {size:,} bytes, mode {oct(mode)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
