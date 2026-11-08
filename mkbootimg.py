#!/usr/bin/env python3
"""
Minimal Android boot image packer (header_version 0/1/2), layout-compatible
with AOSP mkbootimg. Written for ZYBP30 (MT6768) boot repack; reproduces the
stock header exactly (page_size 2048, v2, dtb, absolute addresses with base 0).
"""
import argparse
import os
import struct
import sys

BOOT_MAGIC = b'ANDROID!'


def aligned(value, page):
    return (value + page - 1) // page * page


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kernel', required=True)
    p.add_argument('--ramdisk', default=None)
    p.add_argument('--second', default=None)
    p.add_argument('--dtb', default=None)
    p.add_argument('--recovery_dtbo', default=None)
    p.add_argument('--kernel_addr', type=lambda x: int(x, 0), required=True)
    p.add_argument('--ramdisk_addr', type=lambda x: int(x, 0), required=True)
    p.add_argument('--second_addr', type=lambda x: int(x, 0), default=0)
    p.add_argument('--tags_addr', type=lambda x: int(x, 0), required=True)
    p.add_argument('--dtb_addr', type=lambda x: int(x, 0), default=0)
    p.add_argument('--recovery_dtbo_offset', type=lambda x: int(x, 0), default=0)
    p.add_argument('--page_size', type=int, default=2048)
    p.add_argument('--header_version', type=int, default=2, choices=[0, 1, 2])
    p.add_argument('--os_version', type=lambda x: int(x, 0), default=0,
                   help='raw os_version header field (encodes version+patchlevel)')
    p.add_argument('--board', default='')
    p.add_argument('--cmdline', default='')
    p.add_argument('--extra_cmdline', default='')
    p.add_argument('--id', default='0,0,0,0,0,0,0,0',
                   help='8 comma-separated values for the image id field')
    p.add_argument('-o', '--output', required=True)
    args = p.parse_args()

    page = args.page_size
    if page < 512 or page > 1048576 or page & (page - 1):
        sys.exit('invalid page size: %d' % page)

    kernel = open(args.kernel, 'rb').read()
    ramdisk = open(args.ramdisk, 'rb').read() if args.ramdisk else b''
    second = open(args.second, 'rb').read() if args.second else b''
    dtb = open(args.dtb, 'rb').read() if args.dtb and args.header_version >= 2 else b''
    recovery_dtbo = open(args.recovery_dtbo, 'rb').read() if args.recovery_dtbo and args.header_version >= 1 else b''

    hdr_ver = args.header_version
    if hdr_ver == 0:
        header_size = 1648
    elif hdr_ver == 1:
        header_size = 1652
    else:
        header_size = 1660

    header = bytearray(b'\x00' * header_size)
    header[0:8] = BOOT_MAGIC
    struct.pack_into('<10I', header, 8,
                     len(kernel), args.kernel_addr,
                     len(ramdisk), args.ramdisk_addr,
                     len(second), args.second_addr,
                     args.tags_addr, page, hdr_ver, args.os_version)

    board = args.board.encode()[:16]
    header[48:48 + len(board)] = board

    cmd = args.cmdline.encode()
    if len(cmd) > 512:
        extra = cmd[512:]
        cmd = cmd[:512]
    else:
        extra = args.extra_cmdline.encode()
    header[64:64 + len(cmd)] = cmd
    extra = extra[:1024]
    header[608:608 + len(extra)] = extra

    ids = [int(x, 0) for x in args.id.split(',')]
    if len(ids) != 8:
        sys.exit('--id needs exactly 8 values')
    struct.pack_into('<8I', header, 576, *ids)

    if hdr_ver >= 1:
        struct.pack_into('<IQI', header, 1632,
                         len(recovery_dtbo), args.recovery_dtbo_offset, header_size)
    if hdr_ver >= 2:
        struct.pack_into('<IQ', header, 1648, len(dtb), args.dtb_addr)

    out = bytearray()
    out += header
    out += b'\x00' * (aligned(len(header), page) - len(header))
    for blob in (kernel, ramdisk, second, recovery_dtbo, dtb):
        if blob:
            out += blob
            out += b'\x00' * (aligned(len(blob), page) - len(blob))

    with open(args.output, 'wb') as f:
        f.write(out)
    print('wrote %s (%d bytes): kernel=%d ramdisk=%d second=%d dtb=%d hdr=v%d page=%d'
          % (args.output, len(out), len(kernel), len(ramdisk), len(second),
             len(dtb), hdr_ver, page))


if __name__ == '__main__':
    main()
