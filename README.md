# ZYBP30 (MT6768) Kernel Build — GitHub Actions

This repository builds the **MediaTek MT6768 (k69v1_64_k419)** device kernel
from `WUNELEZI1/Gale-Kernel-Source` branch `mt6768-4.19` and repacks a
flashable `boot_ksu.img` for the ZYBP30 tablet (ZPD1203, Android 12, A/B).

## What was detected from your boot_a.img

| Item | Value |
|------|-------|
| Image format | Android boot image v2 (page 2048), with embedded DTB |
| Current kernel | Linux **4.19.191**, clang 11.0.1 (Android NDK r383902), arm64 SMP PREEMPT |
| Platform | **MediaTek MT6768** (`fstab.mt6768`, `init.recovery.mt6768.rc`, DTB compat `mediatek,mt6768`) |
| Ramdisk | gzip cpio, recovery-as-boot, `buildvariant=user` |
| GKI | ❌ Non-GKI (vendor modules + MTK BSP DTB) |

> ⚠️ Because this is a **non-GKI 4.19 MTK device**, a pure AOSP `android12-5.10`
> GKI kernel will **not boot** on it. This build compiles the device-specific
> **4.19 BSP kernel** (the correct baseline for ZYBP30) with optional KernelSU,
> then repacks it using your stock boot header parameters.

## Build inputs (from stock boot_a.img)

| Parameter | Value |
|-----------|-------|
| `--kernel_offset` | `0x40080000` |
| `--ramdisk_offset` | `0x47c80000` |
| `--tags_offset` | `0x4bc80000` |
| `--dtb_addr` | `0x4bc80000` |
| `--page_size` | `2048` |
| `--header_version` | `2` |
| `--os_version` | `0x18000187` (Android 12) |
| `--cmdline` | `bootopt=64S3,32N2,64N2 buildvariant=user` |
| Ramdisk / DTB | Reused from stock `boot_a.img` |

## How to trigger a build

1. Fork / create this repo under your GitHub account.
2. Enable **Actions** in the repo settings.
3. Go to **Actions → Build ZYBP30 Kernel → Run workflow**.
4. Choose whether to include **KernelSU** (default: yes).
5. When finished, download the `boot_ksu_img` artifact from the run summary.

## Output

- `boot_ksu.img` — repacked boot image (new kernel + stock ramdisk + stock/new DTB).
  Flash with fastboot: `fastboot flash boot_a boot_ksu.img` (or `boot_b` for A/B slot B).

## KernelSU notes

- Uses `tiann/KernelSU` `v1.0.0` (core_hook / ftrace-based mode).
- On 4.19 MTK BSP, core_hook compatibility is **not guaranteed**. If the build
  fails because of KSU, re-run with **with_ksu = false** to get a clean kernel.
- KernelSU Manager APK must be installed separately to manage root.

## Source references

- Kernel source: https://github.com/WUNELEZI1/Gale-Kernel-Source (branch `mt6768-4.19`)
- KernelSU: https://github.com/tiann/KernelSU (tag `v1.0.0`)
- Build precedent: https://github.com/WUNELEZI1/Build_zybp30_kernel
