# 镜像外屏重连修复

此原生插件针对 Hyprland 0.56.2，可在当前桌面加载，无需退出会话。
它跳过镜像目标的接入缩放，在镜像布局变化时完整刷新目标输出，并在源画面尚未准备好时清黑。
内屏动画、分辨率、刷新率和镜像选择保持原有行为。

## 构建与验证

需要与正在运行的 Hyprland 匹配的开发头文件、C++ 编译器和现有像素测试依赖。
在项目根目录执行：

```bash
python3 native/install_hotfix.py --build-only /tmp/mirror-borders-build
python3 tests/mirror_redraw/run.py \
  --baseline-bin /usr/bin/Hyprland \
  --patched-bin /usr/bin/Hyprland \
  --hotfix-plugin /tmp/mirror-borders-build/mirror-borders.so \
  --weston-root /path/to/unpacked-weston \
  --aquamarine-lib /path/to/test-aquamarine-build \
  --output-dir /tmp/mirror-borders-test
```

对照与修复使用同一份合成器程序，仅修复组加载正式插件。
测试读取整片黑边的 RGB 最大值，检查接入的初始帧、重新启用、三次虚拟输出重连、
分辨率变化、旋转和上下黑边；同时检查稳定后的中央画面没有闪黑。
另验证加载器在 Hyprland 自动重读配置后恢复运行时布局，且重复执行不重复加载。

## 安装

通过上述验证后执行：

```bash
python3 native/install_hotfix.py --from-build /tmp/mirror-borders-build
```

程序安装到 `~/.local/share/omarchy-switch-display/mirror-borders/`，
用户服务 `omarchy-mirror-borders.service` 随图形会话加载。
安装前的文件备份在 `~/.local/state/omarchy-switch-display/native-install-*/`。
不需要 root，不替换系统 Hyprland，也不修改登录时的显示配置。

Hyprland 加载原生插件时会重读配置。加载器等待对应事件，再恢复加载前的运行时布局。
插件在加载前检查编译时与运行时 ABI；Hyprland 升级导致 ABI 改变后，加载器跳过旧插件，需要重新构建。

## 移除

```bash
systemctl --user disable --now omarchy-mirror-borders.service
hyprctl plugin unload "$HOME/.local/share/omarchy-switch-display/mirror-borders/mirror-borders.so"
```

卸载原生插件也会让 Hyprland 重读显示配置。

2026-10-20：正式插件的隔离像素测试与当前会话外屏关闭、恢复检查通过。
真实 HDMI 拔插后的可见效果仍需在外屏确认。
