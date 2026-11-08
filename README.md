# KernelSU Next boot image build for ZYB ZPD1203 (MT6768)

本目录用于在 **GitHub Actions** 云端编译 ZPD1203 (MT6768, Android 12, A/B) 的
KernelSU Next 集成内核，并重打包为 `boot.img` + `AnyKernel3.zip`。

## 设备信息

| 项目 | 值 |
|------|-----|
| 设备 | ZYB ZPD1203 / ZYBP30 |
| 平台 | MediaTek MT6768 |
| 板型 | k69v1_64_k419 |
| Android | 12 |
| 分区 | A/B (boot_a / boot_b) |
| 内核 | Linux 4.19.191 |
| SU 方案 | KernelSU Next (v3.x, dev 分支) |
| 启动镜像 | Android boot image v2 (ANDROID! magic), page_size 2048, dtb 嵌入 boot |

## 目录结构

```
kbuild/
├── .github/workflows/kernel-su-next.yml   # GitHub Actions 编译工作流
├── scripts/repack_boot.sh                  # boot.img 重打包脚本 (纯 shell)
├── anykernel3/anykernel.sh                 # AnyKernel3 安装脚本 (模板)
├── anykernel3/META-INF/com/google/android/updater-script
├── boot_a.img                              # <-- 放入你的原厂 boot_a.img (33,554,432 字节)
└── README.md                               # 本文件
```

## 准备工作 (由你在 GitHub 完成)

1. **Fork 或创建一个仓库**，把本目录 (`kbuild/` 的全部内容) 推上去。
2. 将你设备的原厂 `boot_a.img` 放到仓库根目录，文件名必须为 `boot_a.img`。
   - 大小应为 33,554,432 字节 (32 MiB)。
   - 如果没有 `boot_a.img`，可用 `boot_b.img` 重命名。
3. 在仓库的 **Actions** 页面启用 workflow，手动触发 `Build KernelSU Next boot image for ZPD1203 (MT6768)`。

## 工作流做什么

1. 安装交叉编译工具链 (`aarch64-linux-gnu-gcc` 等)。
2. 克隆 `WUNELEZI1/Gale-Kernel-Source` (分支 `mt6768-4.19`) 作为内核源码。
3. 集成 `KernelSU-Next` (分支 `dev`)：
   - `drivers/kernelsu` 符号链接
   - `drivers/Makefile` 追加 `obj-$(CONFIG_KSU) += kernelsu/`
   - `drivers/Kconfig` 追加 `source "drivers/kernelsu/Kconfig"`
4. 使用 `k69v1_64_k419_defconfig`，并补全 KernelSU-Next 所需配置：
   - `CONFIG_MODULES=y`, `CONFIG_EXT4_FS=y`, `CONFIG_KPROBES=y`, `CONFIG_KSU=y`
5. 交叉编译 arm64 `Image.gz` (版本字符串设为 `4.19.191-ksu`)。
6. 用 `scripts/repack_boot.sh` 从 `boot_a.img` 提取原 ramdisk + dtb + cmdline，替换内核，重新打包 v2 header (偏移与原镜像一致)。
7. 打包 `AnyKernel3.zip` (支持 boot_a + boot_b)。
8. 上传 `boot_a_ksu.img` 和 `anykernel3-zpd1203-ksu.zip` 作为构建 artifact (保留 7 天)。

## 关键参数 (与原镜像保持一致)

```
--page_size 2048
--header_version 2
--kernel_addr   0x40080000
--ramdisk_addr  0x47c80000
--tags_addr     0x4bc80000
--cmdline       bootopt=64S3,32N2,64N2 buildvariant=user
```

重打包脚本 `scripts/repack_boot.sh` 会从原 `boot_a.img` 自动读取并保留：
- ramdisk (gzip cpio) 和 dtb (MTK 魔数 d7b7ab1e)
- cmdline (`bootopt=64S3,32N2,64N2 buildvariant=user`)
- page size、header size、各分区偏移

## 刷入方式

构建完成后从 Actions artifact 下载：

**方法 A — AnyKernel3 (推荐，recovery 刷入)**
1. 将 `anykernel3-zpd1203-ksu.zip` 放入手机内存或 U 盘。
2. 进入 TWRP / OrangeFox 等 recovery。
3. 选择 Install → 选中该 zip → 刷入。
4. 重启。

**方法 B — fastboot (A/B 分区)**
```
fastboot flash boot_a boot_a_ksu.img
fastboot flash boot_b boot_a_ksu.img   # 同一镜像刷入两个槽位
fastboot reboot
```

## 事后

- 安装 **KernelSU Manager APK** 以获取 root 管理界面（工作流不包含 APK，需自行从 KernelSU-Next 官方下载）。
- 如需修改内核配置，编辑工作流中 `Configure kernel` 步骤追加的 `.config` 行，或在构建前插入 `make menuconfig`（需交互，不适合云端）。
- 如编译失败，查看 Actions 日志中的 `Configure kernel` / `Build kernel` 输出，核对 defconfig 名称与源码分支。

## 注意事项

- 本工作流使用 `workflow_dispatch` 手动触发，不会定时自动编译。
- `boot_a.img` 不应上传到公开仓库（属于设备固件），建议使用私有仓库。
- 构建 artifact 保留 7 天，请及时下载。

<!-- build trigger -->

<!-- trigger -->
