#!/bin/bash
# pack_boot.sh - Build ZYBP30 (MT6768) kernel and repack boot image.
#
# Env vars:
#   WITH_KSU   - "true" to integrate KernelSU (default: true)
#   KSU_REF    - KernelSU tag/branch (default: v1.0.0)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

WITH_KSU="${WITH_KSU:-true}"
KSU_REF="${KSU_REF:-v1.0.0}"

echo "=== [1/6] Unpack stock boot_a.img ==="
python3 unpack_bootimg.py boot_a.img
ls -lh unpacked_ramdisk.gz unpacked_dtb

echo "=== [2/6] Clone Gale kernel source (mt6768-4.19) ==="
rm -rf kernel-source
git clone --depth=1 --branch mt6768-4.19 https://github.com/WUNELEZI1/Gale-Kernel-Source.git kernel-source

KSU_OK=false
if [ "$WITH_KSU" = "true" ]; then
  echo "=== [3/6] Integrate KernelSU ($KSU_REF) ==="
  cd kernel-source
  if git clone --depth=1 --branch "$KSU_REF" https://github.com/tiann/KernelSU.git ksutmp; then
    # Copy KernelSU kernel/ into drivers/kernelsu/ (real dir, not symlink, so relative include paths work)
    rm -rf drivers/kernelsu
    mkdir -p drivers/kernelsu
    cp -r ksutmp/kernel/. drivers/kernelsu/
    rm -rf ksutmp

    # drivers/Makefile: build kernelsu when CONFIG_KSU=y
    if ! grep -q "kernelsu" drivers/Makefile; then
      printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> drivers/Makefile
    fi

    # drivers/Kconfig: source kernelsu Kconfig (insert before trailing endmenu)
    if ! grep -q "kernelsu" drivers/Kconfig; then
      sed -i '/^[[:space:]]*endmenu[[:space:]]*$/i\    source "drivers/kernelsu/Kconfig"' drivers/Kconfig
    fi

    cd ..
    KSU_OK=true
    echo "[+] KernelSU integrated into drivers/kernelsu/"
  else
    echo "[!] KernelSU clone failed — building clean kernel"
  fi
fi

echo "=== [4/6] Pin kernel SUBLEVEL to 191 (match stock vermagic) ==="
sed -i 's/^SUBLEVEL = .*/SUBLEVEL = 191/' kernel-source/Makefile

echo "=== [5/6] Defconfig + build ==="
cd kernel-source
make ARCH=arm64 k69v1_64_k419_defconfig

if [ "$KSU_OK" = "true" ]; then
  # Enable KSU + ftrace prerequisites (core_hook needs dynamic ftrace on arm64 4.19)
  sed -i 's/^CONFIG_KSU=.*/CONFIG_KSU=y/' .config 2>/dev/null || echo "CONFIG_KSU=y" >> .config
  for opt in CONFIG_DYNAMIC_FTRACE CONFIG_HAVE_DYNAMIC_FTRACE CONFIG_HAVE_ARCH_FTRACE CONFIG_FTRACE_MCOUNT_RECORD; do
    sed -i "/^$opt=/d" .config
    echo "$opt=y" >> .config
  done
  # KSU manager package name (optional)
  sed -i '/^CONFIG_KSU_MANAGER_PACKAGE=/d' .config
  echo 'CONFIG_KSU_MANAGER_PACKAGE="com.kernel.manager"' >> .config
fi

make ARCH=arm64 olddefconfig >/dev/null 2>&1 || true

# Verify key config
grep -E "^CONFIG_KSU=|^CONFIG_MTK_PLATFORM=|^CONFIG_ARCH_MTK_PROJECT=" .config || true

make ARCH=arm64 -j"$(nproc)" \
  CROSS_COMPILE=aarch64-linux-gnu- \
  CC=clang CLANG_TRIPLE=aarch64-linux-gnu- \
  LD=ld.lld \
  Image.gz dtbs 2>&1 | tee build.log

cd ..

echo "=== [6/6] Pack boot image ==="
DTB="$(find kernel-source/arch/arm64/boot/dts -name '*.dtb' 2>/dev/null | head -1 || true)"
if [ -z "$DTB" ]; then
  echo "[!] No dtb in source tree — using stock dtb from boot_a.img"
  DTB="$REPO_ROOT/unpacked_dtb"
else
  echo "[+] Using source-tree DTB: $DTB"
fi

python3 mkbootimg.py \
  --kernel kernel-source/arch/arm64/boot/Image.gz \
  --ramdisk unpacked_ramdisk.gz \
  --dtb "$DTB" \
  --kernel_addr 0x40080000 \
  --ramdisk_addr 0x47c80000 \
  --tags_addr 0x4bc80000 \
  --dtb_addr 0x4bc80000 \
  --page_size 2048 \
  --header_version 2 \
  --os_version 0x18000187 \
  --board '' \
  --cmdline 'bootopt=64S3,32N2,64N2 buildvariant=user' \
  --id '0x54604684,0xae20ab2f,0xe5fc3fbc,0x305f50d9,0x1c38399f,0,0,0' \
  -o boot_ksu.img

ls -lh boot_ksu.img
echo "=== DONE: boot_ksu.img ==="
