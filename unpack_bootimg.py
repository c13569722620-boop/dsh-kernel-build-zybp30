#!/usr/bin/env python3
"""Minimal Android boot image unpacker (v0/1/2) + header dump.
Used by the CI round-trip test: unpack stock boot_a.img, then repack the
exact same blobs and byte-compare against the original file."""
import gzip
import io
import struct
import sys


def main():
    data = open(sys.argv[1], 'rb').read()
    if data[:8] != b'ANDROID!':
        sys.exit('not an android boot image')
    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
     second_size, second_addr, tags_addr, page_size,
     hdr_ver, os_ver) = struct.unpack_from('<10I', data, 8)
    board = data[48:64].split(b'\x00')[0].decode(errors='replace')
    cmdline = data[64:576].split(b'\x00')[0].decode(errors='replace')
    extra = data[608:1632].split(b'\x00')[0].decode(errors='replace')
    recovery_dtbo_size = recovery_dtbo_offset = 0
    dtb_size = dtb_addr = 0
    if hdr_ver >= 1:
        recovery_dtbo_size, recovery_dtbo_offset, header_size = struct.unpack_from('<IQI', data, 1632)
    if hdr_ver >= 2:
        dtb_size, dtb_addr = struct.unpack_from('<IQ', data, 1648)

    def align(v):
        return (v + page_size - 1) // page_size * page_size

    koff = page_size
    roff = align(koff + kernel_size)
    soff = align(roff + ramdisk_size)
    recovery_dtbo_offset_abs = align(soff + second_size)
    doff = align(recovery_dtbo_offset_abs + recovery_dtbo_size)

    print('kernel_size=%d ramdisk_size=%d second_size=%d recovery_dtbo_size=%d dtb_size=%d'
          % (kernel_size, ramdisk_size, second_size, recovery_dtbo_size, dtb_size))
    print('kernel_addr=0x%x ramdisk_addr=0x%x second_addr=0x%x tags_addr=0x%x dtb_addr=0x%x'
          % (kernel_addr, ramdisk_addr, second_addr, tags_addr, dtb_addr))
    print('page_size=%d header_version=%d os_version=0x%x header_size=%s'
          % (page_size, hdr_ver, os_ver, header_size if hdr_ver >= 1 else '1648'))
    print('board=%r cmdline=%r extra=%r' % (board, cmdline, extra))
    print('offsets: kernel=%d ramdisk=%d second=%d dtb=%d end_of_image=%d'
          % (koff, roff, soff, doff, align(doff + dtb_size)))

    open('unpacked_kernel.gz', 'wb').write(data[koff:koff + kernel_size])
    open('unpacked_ramdisk.gz', 'wb').write(data[roff:roff + ramdisk_size])
    if second_size:
        open('unpacked_second', 'wb').write(data[soff:soff + second_size])
    if dtb_size:
        open('unpacked_dtb', 'wb').write(data[doff:doff + dtb_size])

    with gzip.open(io.BytesIO(data[koff:koff + kernel_size]), 'rb') as f:
        img = f.read()
    i = img.find(b'Linux version')
    print('kernel banner: %s' % img[i:i + 200].split(b'\x00')[0].decode(errors='replace'))


if __name__ == '__main__':
    main()
