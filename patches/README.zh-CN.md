# Hyprland 0.56.2 镜像刷新修复

补丁针对 Hyprland `v0.56.2`，提交
`efb50993780079460b0cbed1363e2166a2de1d9f`。
它修复合成器中的镜像刷新问题；现有安装脚本不会应用补丁或替换正在运行的 Hyprland。

## 修改内容

- 镜像关系改变时，将整个目标输出加入刷新区域历史，并强制完整渲染最初三帧。
- 镜像源或目标应用显示规则后，重新刷新受影响的镜像输出，包括等比缩放留下的边缘。
- 新镜像连接到静止桌面时，主动请求源画面，生成镜像缓冲区。
- 传播刷新区域前先取得有效的镜像显示器强引用，跳过已断开的输出。
- 镜像目标不参与接入时的放大、缩小过渡，避免旧窗口像素进入黑边后停留或闪动。
- 镜像源尚未生成画面缓冲区时，先将目标清黑。

正常使用时继续保留局部刷新。补丁不修改分辨率策略、刷新率、工作区策略或用户配置。

## 独立构建

在独立的 Hyprland 源码目录准备上述版本及其子模块、构建依赖后执行：

```bash
git apply --check /path/to/omarchy-switch-display/patches/hyprland-0.56.2-mirror-redraw.patch
git apply /path/to/omarchy-switch-display/patches/hyprland-0.56.2-mirror-redraw.patch
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DNO_HYPRPM=ON
nice -n 15 cmake --build build --target Hyprland -j 4
```

这些操作只生成 `build/Hyprland`，不安装、不启动，也不重新加载当前桌面。

## 像素回归测试

测试使用 Bubblewrap 隔离挂载、进程、网络及运行目录，内部启动 Weston 无界面后端和
第二个 Hyprland。仅开放 DRM 渲染节点，不开放 KMS 显示设备、输入设备、会话总线或
当前桌面的控制套接字。探针拒绝在普通桌面运行；预置旧画面和断开操作仅针对测试
合成器的 headless 输出。

需要 C++ 编译器、当前版本 Hyprland 开发头文件、Bubblewrap、独立解包的 Weston 及其
依赖，以及独立构建的 Aquamarine 0.15.0。Aquamarine 原版固定请求 Wayland compositor
v6，而 Weston 15 提供 v5；先在**测试专用** Aquamarine 源码目录应用
`tests/mirror_redraw/aquamarine-parent-compat.patch`，再用 CMake 构建。
对照和补丁测试使用同一份测试库。无需安装 Weston 或该测试库。

```bash
nice -n 15 python tests/mirror_redraw/run.py \
  --patched-bin /path/to/Hyprland/build/Hyprland \
  --weston-root /path/to/unpacked-weston-package \
  --aquamarine-lib /path/to/aquamarine/build \
  --output-dir /tmp/mirror-redraw-results
```

`--weston-root` 中应有 `usr/bin/weston` 和 `usr/lib`；单独解包的依赖放入同一目录。
默认对照程序为 `/usr/bin/Hyprland`，可用 `--baseline-bin` 指定。
默认渲染节点为 `/dev/dri/renderD128`，可用 `--render-node` 指定其他渲染节点。

测试在三个复用输出缓冲区中预置不同旧内容，然后读取真实合成器输出的整片黑边
（仅略过紧邻画面的一个滤波像素）和中央像素。每个场景至少读取九帧，
同时检查稳定后的中央画面仍正常显示。镜像目标的实际分辨率逐阶段验证为 3840×2160。

2026-10-20 验证结果（对照为已安装的首版镜像补丁 `0.56.2-2.1`）：

| 场景 | 首版镜像补丁 | 本次修复 |
| --- | --- | --- |
| 首次进入镜像、源分辨率改变 | 边缘出现旧画面 | 采样黑边始终为黑色 |
| 外屏关闭后重新启用镜像 | 左侧保留源画面 | 采样黑边始终为黑色 |
| 镜像目标旋转 180°、源旋转 90° | 此轮未复现残影 | 采样黑边始终为黑色 |
| 解除后重新进入镜像 | 此轮未复现残影 | 采样黑边始终为黑色 |
| 镜像目标连续断开、重连三次 | 此轮未执行 | 无崩溃，镜像恢复，黑边无残影帧 |
| 源画面变宽形成上下黑边 | 此轮未复现残影 | 上下黑边保持黑色 |

完整 Hyprland 编译及现有插件的 31 项 Python 回归测试通过。
同一组像素测试还验证了[正式运行时插件](../native/README.zh-CN.md)。
这些结果验证了隔离合成器的像素刷新和虚拟输出重连；实际 HDMI 链路的可见效果仍需确认。

本机已安装保留 XWayland、systemd 和 UWSM 支持的本地包 `hyprland 0.56.2-2.1`。
安装前对最终程序重复了上述隔离测试，并确认包内程序与测试程序的哈希一致。
当前会话已加载首版合成器补丁，并通过用户服务加载本次运行时插件，无需重启桌面。
系统 Hyprland 软件包未被本次修复替换。原版软件包、安装记录和回退脚本保存在
`~/.local/state/omarchy-switch-display/hyprland-mirror-fix-20261019/`。
后续官方 Hyprland 升级可能替换这份本地补丁。
