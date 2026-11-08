#!/usr/bin/env bash
#
# repack_boot.sh — repack an Android boot image (v2 header) with a new kernel.
#
# Usage:
#   bash repack_boot.sh --kernel Image.gz --ramdisk ramdisk.cpio.gz --dtb dtb.img \
#       --cmdline "bootopt=..." --out boot_a_ksu.img
#
# Or extract ramdisk/dtb from an existing boot image:
#   bash repack_boot.sh --extract boot_a.img --kernel Image.gz --out boot_a_ksu.img
#
# Pure bash + coreutils (dd, cat, head, wc, od). No python / xxd required.
#
set -euo pipefail

PAGE_SIZE=2048
HEADER_FIXED=1660        # bytes of the fixed v2 header before padding (MTK layout: fields at 1644/1648/1652)

KERNEL=""
RAMDISK=""
DTB=""
CMDLINE=""
OUT=""
EXTRACT=""
KERNEL_ADDR="0x40080000"
RAMDISK_ADDR="0x47c80000"
TAGS_ADDR="0x4bc80000"
HEADER_VERSION=2

while [ $# -gt 0 ]; do
  case "$1" in
    --kernel)      KERNEL="$2"; shift 2 ;;
    --ramdisk)     RAMDISK="$2"; shift 2 ;;
    --dtb)         DTB="$2"; shift 2 ;;
    --cmdline)     CMDLINE="$2"; shift 2 ;;
    --page-size)   PAGE_SIZE="$2"; shift 2 ;;
    --header-version) HEADER_VERSION="$2"; shift 2 ;;
    --kernel-addr) KERNEL_ADDR="$2"; shift 2 ;;
    --ramdisk-addr) RAMDISK_ADDR="$2"; shift 2 ;;
    --tags-addr)   TAGS_ADDR="$2"; shift 2 ;;
    --extract)     EXTRACT="$2"; shift 2 ;;
    --out)         OUT="$2"; shift 2 ;;
    *) echo "error: unknown argument '$1'" >&2; exit 1 ;;
  esac
done

if [ -z "$OUT" ]; then
  echo "error: --out is required" >&2; exit 1
fi

# ---------------------------------------------------------------------------
# Read a little-endian u32 from a file at a given offset (GNU od).
# ---------------------------------------------------------------------------
u32_le() { # file offset
  od -An -tu4 --endian=little -j "$2" -N 4 "$1" 2>/dev/null | tr -d ' \n'
}

# write a little-endian u32 to stdout (4 raw bytes)
write_u32_le() { # value_dec
  local v="$1"
  printf "\\$(printf '%03o' $(( v        & 255 )))" \
         "\\$(printf '%03o' $(( (v>>8)  & 255 )))" \
         "\\$(printf '%03o' $(( (v>>16) & 255 )))" \
         "\\$(printf '%03o' $(( (v>>24) & 255 )))"
}

# ---------------------------------------------------------------------------
# Build (or extract+modify) the fixed 1624-byte header into $TMP/header.bin
# ---------------------------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "$EXTRACT" ]; then
  if [ ! -f "$EXTRACT" ]; then
    echo "error: --extract file not found: $EXTRACT" >&2; exit 1
  fi
  head -c "$HEADER_FIXED" "$EXTRACT" > "$TMP/header.bin"
  PS=$(u32_le "$EXTRACT" 36)
  [ -n "$PS" ] || PS="$PAGE_SIZE"
  KSZ=$(u32_le "$EXTRACT" 8)
  RSZ=$(u32_le "$EXTRACT" 16)
  DSZ=$(u32_le "$EXTRACT" 1648)
  KOFF=$PS
  ROFF=$(( (KOFF + KSZ + PS - 1) / PS * PS ))
  DOFF=$(( (ROFF + RSZ + PS - 1) / PS * PS ))
  # extract ramdisk and dtb blobs
  dd if="$EXTRACT" of="$TMP/ramdisk.cpio.gz" bs=1 skip="$ROFF" count="$RSZ" status=none
  dd if="$EXTRACT" of="$TMP/dtb.img" bs=1 skip="$DOFF" count="$DSZ" status=none
  RAMDISK="$TMP/ramdisk.cpio.gz"
  DTB="$TMP/dtb.img"
  # keep original cmdline unless overridden
  if [ -z "$CMDLINE" ]; then
    CMDLINE=$(dd if="$EXTRACT" bs=1 skip=64 count=512 status=none | tr -d '\0')
  fi
  KERNEL_ADDR="0x$(u32_le "$EXTRACT" 12 | awk '{printf "%x",$1}')"
  RAMDISK_ADDR="0x$(u32_le "$EXTRACT" 20 | awk '{printf "%x",$1}')"
  TAGS_ADDR="0x$(u32_le "$EXTRACT" 32 | awk '{printf "%x",$1}')"
  HEADER_VERSION=$(u32_le "$EXTRACT" 40)
else
  if [ -z "$KERNEL" ] || [ -z "$RAMDISK" ] || [ -z "$DTB" ]; then
    echo "error: --kernel --ramdisk --dtb are required (or use --extract)" >&2; exit 1
  fi
  PS="$PAGE_SIZE"
  : > "$TMP/header.bin"
  {
    printf 'ANDROID!'
    write_u32_le 0               # kernel_size (patched below)
    write_u32_le "$((KERNEL_ADDR))"
    write_u32_le 0               # ramdisk_size (patched below)
    write_u32_le "$((RAMDISK_ADDR))"
    write_u32_le 0               # second_size
    write_u32_le 0               # second_addr
    write_u32_le "$((TAGS_ADDR))"
    write_u32_le "$PS"
    write_u32_le "$HEADER_VERSION"
    write_u32_le 0               # os_version
  } >> "$TMP/header.bin"
  # name[16] @48, cmdline[512] @64, id[8] @576, extra_cmdline[1024] @584
  # MTK layout: 36 bytes zeros after extra_cmdline, then header_size@1644, dtb_size@1648, dtb_addr@1652
  {
    head -c 16 /dev/zero         # name (empty)
    if [ -n "$CMDLINE" ]; then
      printf '%-512.512s' "$CMDLINE"
    else
      head -c 512 /dev/zero
    fi
    head -c 8 /dev/zero          # id
    head -c 1024 /dev/zero       # extra_cmdline
    head -c 36 /dev/zero         # padding to offset 1644
    write_u32_le "$HEADER_FIXED" # header_size @1644
    write_u32_le 0               # dtb_size (patched below) @1648
    write_u32_le 0               # dtb_addr @1652
    head -c 4 /dev/zero          # padding to 1660
  } >> "$TMP/header.bin"
fi

# ---------------------------------------------------------------------------
# Patch size fields into the header (kernel_size @8, ramdisk_size @16,
# dtb_size @1616).
# ---------------------------------------------------------------------------
patch_u32() { # file offset value_dec
  local f="$1" off="$2" val="$3"
  write_u32_le "$val" | dd of="$f" bs=1 seek="$off" count=4 conv=notrunc status=none
}

KSZ=$(wc -c < "$KERNEL" | tr -d ' ')
RSZ=$(wc -c < "$RAMDISK" | tr -d ' ')
DSZ=$(wc -c < "$DTB" | tr -d ' ')

patch_u32 "$TMP/header.bin" 8  "$KSZ"
patch_u32 "$TMP/header.bin" 16 "$RSZ"
patch_u32 "$TMP/header.bin" 1648 "$DSZ"

# cmdline: only patch in non-extract mode (extract mode already set CMDLINE from original)
if [ -z "$EXTRACT" ] && [ -n "$CMDLINE" ]; then
  {
    printf '%s' "$CMDLINE"
    if [ ${#CMDLINE} -lt 512 ]; then head -c $((512 - ${#CMDLINE})) /dev/zero; fi
  } | dd of="$TMP/header.bin" bs=1 seek=64 count=512 conv=notrunc status=none
fi

# ---------------------------------------------------------------------------
# Assemble output image
# ---------------------------------------------------------------------------
KOFF=$PS
ROFF=$(( (KOFF + KSZ + PS - 1) / PS * PS ))
DOFF=$(( (ROFF + RSZ + PS - 1) / PS * PS ))

{
  cat "$TMP/header.bin"
  head -c $((PS - HEADER_FIXED)) /dev/zero
  cat "$KERNEL"
  cur=$((PS + KSZ))
  if [ "$cur" -lt "$ROFF" ]; then head -c $((ROFF - cur)) /dev/zero; fi
  cat "$RAMDISK"
  cur=$((ROFF + RSZ))
  if [ "$cur" -lt "$DOFF" ]; then head -c $((DOFF - cur)) /dev/zero; fi
  cat "$DTB"
} > "$OUT"

echo "wrote $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"
echo "  kernel: off=$KOFF size=$KSZ"
echo "  ramdisk: off=$ROFF size=$RSZ"
echo "  dtb: off=$DOFF size=$DSZ"
echo "  cmdline: ${CMDLINE:-<original>}"
echo "  page_size=$PS header_version=$HEADER_VERSION"
echo "  kernel_addr=$KERNEL_ADDR ramdisk_addr=$RAMDISK_ADDR tags_addr=$TAGS_ADDR"
