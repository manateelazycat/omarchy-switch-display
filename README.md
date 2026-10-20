# Omarchy Switch Display

![Preview](preview.png)

[简体中文](README.zh-CN.md)

A minimal display layout picker for Omarchy Shell. Use **Super+P** to switch
between extend, mirror, internal-only, and external-only modes.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Hold `Super` and press `P` | Open the layout preview. |
| Keep holding `Super` and press `P` again | Preview the next layout. |
| Release both `Super` and `P` | Apply the selected layout and close the preview. |

## Features

- Four display modes: extend, mirror, internal only, and external only.
- Single-display modes use each display's largest supported resolution.
- Session-only changes; saved monitor profiles and login configuration stay intact.
- Simple SVG outline icons with consistent strokes and clear mode previews.
- Live Omarchy theme colors, fonts, spacing, borders, and system corner rounding.
- Staged transitions, output readiness checks, and recovery after failed switches.

## Requirements

Omarchy Shell with its plugin system, Quickshell global shortcuts, Python 3,
Qt Quick VectorImage/Effects, and Hyprland's Lua monitor API and `hl.is_key_down`.

Tested with Omarchy 4.0.4, Hyprland 0.56.2, and Qt 6.11.2. If Hyprmoncfg is
installed, switch it to manual management before using this plugin.

Hyprland 0.56.2 can crash when an external display disconnects during mirroring.
Use an extended login layout on that version. See the
[development notes (Chinese)](docs/CHANGELOG.zh-CN.md) for the investigation.

For mirror border artifacts on Hyprland 0.56.2, a compositor patch and isolated
pixel regression test are available in [patches](patches/README.zh-CN.md).
The plugin installer does not apply this patch or replace Hyprland.
An optional [runtime fix](native/README.zh-CN.md) keeps mirror borders black
after reconnecting without restarting the desktop.

## Install

```bash
git clone https://github.com/manateelazycat/omarchy-switch-display.git
cd omarchy-switch-display
./install.sh
omarchy restart shell
```

Keep the checkout in place: the installer links it to
`~/.config/omarchy/plugins/andy.switch-display`. It enables the plugin, backs up
`~/.config/hypr/bindings.lua`, and replaces the existing **Super+P** binding.

Installation reloads Hyprland's saved monitor configuration. Restarting Omarchy
Shell ensures that the latest plugin code and icons are loaded.

## Update

Run from the existing checkout:

```bash
git pull --ff-only
./install.sh
omarchy restart shell
```

## Remove

```bash
omarchy plugin remove andy.switch-display --yes
```

Remove the block beginning with
`-- Switch display layouts with the standalone picker.` from
`~/.config/hypr/bindings.lua`, including its following `hl.unbind` and `hl.bind`
lines. Reload Hyprland to restore the previous Super+P behavior:

```bash
hyprctl reload
hyprctl configerrors
```

## Development

```bash
python3 -m unittest discover -s tests -v
omarchy plugin validate .
/usr/lib/qt6/bin/qmlformat --normalize Service.qml >/dev/null
/usr/lib/qt6/bin/qmlformat --normalize DisplayLayoutIcon.qml >/dev/null
/usr/lib/qt6/bin/qmllint DisplayLayoutIcon.qml
bash -n install.sh
```

These checks do not change the display layout. Inspect the running picker with:

```bash
omarchy-shell andy.switch-display status
```

## License

Copyright (C) 2026 Andy Stewart.

GPL-3.0-only. See [LICENSE](LICENSE).
