#!/usr/bin/env python3
"""Split a ramdisk into its gzip member part and any trailing xz member.

The ZPD1203 ramdisk layout is:

    [ gzip(main cpio) ][ xz(wireless modules cpio) ]

The kernel's initramfs unpacker handles concatenated members, but our repair
tools need the gzip part isolated so they can rewrite it without disturbing
the appended xz blob.

Usage: split_ramdisk_tail.py <in> <out_gz> <out_tail>
Writes out_gz (the gzip member bytes) and out_tail (everything after, possibly
empty). Prints a summary.
"""
import sys
import zlib


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: split_ramdisk_tail.py <in> <out_gz> <out_tail>", file=sys.stderr)
        return 2
    src, out_gz, out_tail = sys.argv[1:4]

    raw = open(src, "rb").read()
    pos = 0
    members = 0
    while pos < len(raw) and raw[pos:pos + 2] == b"\x1f\x8b":
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        d.decompress(raw[pos:])
        consumed = len(raw) - pos - len(d.unused_data)
        if consumed <= 0:
            break
        members += 1
        pos += consumed

    gz = raw[:pos]
    tail = raw[pos:]

    open(out_gz, "wb").write(gz)
    open(out_tail, "wb").write(tail)

    print(f"[ok] {src}: {len(raw):,} bytes")
    print(f"     gzip members: {members}, gz part {len(gz):,}, tail {len(tail):,}")
    if tail:
        magic = tail[:6].hex()
        kind = "xz" if tail[:6] == b"\xfd7zXZ\x00" else "unknown"
        print(f"     tail magic {magic} ({kind})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
