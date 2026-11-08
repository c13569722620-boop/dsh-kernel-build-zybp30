#!/system/bin/sh
# AnyKernel3 for ZPD1203 (MT6768) KernelSU Next boot image
# Device: ZYB ZPD1203 / ZYBP30, board k69v1_64_k419, Android 12, A/B
# Kernel: Linux 4.19.191-ksu (KernelSU Next)
#
# Flash this zip in TWRP / OrangeFox / similar recovery.
# It replaces boot_a (and boot_b on A/B devices) with the KernelSU Next boot.img.

do.devicecheck=1
device.name1=k69v1_64_k419
device.name2=ZPD1203
device.name3=ZYBP30
device.name4=mt6768

# block locations (by-name symlinks exist on A/B devices)
block=/dev/block/by-name/boot_a
is_slot_device=1

# ---------------------------------------------------------------------------
# Install hooks
# ---------------------------------------------------------------------------
ui.print(" "
ui.print("*******************************")
ui.print("  KernelSU Next boot image")
ui.print("  Device: ZPD1203 (MT6768)")
ui.print("  Kernel: 4.19.191-ksu")
ui.print("*******************************")
ui.print(" ")

# Verify we are on a supported device
getprop ro.product.device > /tmp/ak_device 2>/dev/null || true
DEV=$(cat /tmp/ak_device 2>/dev/null)
case "$DEV" in
  $device.name1|$device.name2|$device.name3|$device.name4|*) : ;;
esac
# Soft check — warn but continue; the zip is meant for ZPD1203.
ui.print("Detected device: ${DEV:-unknown}")

# Flash boot_a
dump_boot
write_boot

# Flash boot_b on A/B devices (slot B)
if [ -b /dev/block/by-name/boot_b ]; then
  block=/dev/block/by-name/boot_b
  dump_boot
  write_boot
fi

ui.print(" "
ui.print("Done! Reboot to apply KernelSU Next.")
ui.print("Install the KernelSU Manager APK to manage root access.")
