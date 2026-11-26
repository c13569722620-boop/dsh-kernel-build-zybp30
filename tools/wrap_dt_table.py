#!/usr/bin/env python3
"""Wrap one or more FDT (.dtb) files in an Android DT Table (magic 0xd7b7ab1e),
matching the exact inline DT table format found in stock MT6768 boot_a.img's DTB slot.

Usage: wrap_dt_table.py <in.dtb> <out.dtimg> [--page-size 2048] [--id 0] [--rev 0]
"""
import argparse
import struct
from pathlib import Path

DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_MAGIC = b"\xd0\x0d\xfe\xed"


def wrap_single(dtb: bytes, page_size: int = 2048, dt_id: int = 0, dt_rev: int = 0) -> bytes:
    if len(dtb) < 40 or dtb[:4] != FDT_MAGIC:
        raise ValueError("Input is not a valid FDT (missing 0xd00dfeed magic)")
    header_size = 32
    entry_size = 32
    entries_offset = header_size
    dt_offset = header_size + entry_size  # 0x40
    total_size = dt_offset + len(dtb)

    hdr = struct.pack(
        ">8I",
        DT_TABLE_MAGIC,
        total_size,
        header_size,
        entry_size,
        1,               # dt_entry_count
        entries_offset,
        page_size,
        0,               # version
    )
    entry = struct.pack(
        ">8I",
        len(dtb),
        dt_offset,
        dt_id,
        dt_rev,
        0, 0, 0, 0,      # custom[4]
    )
    return hdr + entry + dtb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_dtb", type=Path)
    ap.add_argument("output_dtimg", type=Path)
    ap.add_argument("--page-size", type=int, default=2048)
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--rev", type=int, default=0)
    args = ap.parse_args()

    out = wrap_single(args.input_dtb.read_bytes(), args.page_size, args.id, args.rev)
    args.output_dtimg.parent.mkdir(parents=True, exist_ok=True)
    args.output_dtimg.write_bytes(out)
    print(f"Wrapped {args.input_dtb} ({args.input_dtb.stat().st_size} B) -> {args.output_dtimg} ({len(out)} B)")


if __name__ == "__main__":
    main()
