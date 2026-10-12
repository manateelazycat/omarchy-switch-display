# Switch Display

[中文说明](README.zh-CN.md) · [GPL-3.0](LICENSE)

A standalone display layout picker for Omarchy Shell and Hyprland. Hold **Super** and press **P** to preview a layout. Keep holding Super and press P again to cycle through the four modes. The selected layout is applied after both keys are released.

![Switch Display layout picker](docs/preview.png)

| Mode | Behavior |
| --- | --- |
| Extend | Use the connected displays side by side. |
| Mirror | Show the same content on all connected displays. |
| Internal only | Use the built-in display at its largest supported resolution. |
| External only | Use external displays at their largest supported resolutions. |

Changes apply to the current session. The plugin does not save monitor profiles or modify login monitor configuration. Its device icons use simple SVG outlines: side-by-side devices for extension, overlapping screens for mirroring, and laptop or monitor silhouettes for single-display modes.

## Requirements

- Omarchy Shell with its plugin system and Quickshell global shortcuts.
- Hyprland with the Lua monitor API, `hyprctl eval`, and `hl.is_key_down`.
- Python 3 and Qt Quick VectorImage with the curve renderer.
- Manual display management if `hyprmoncfg` is installed; the plugin rejects changes while its daemon manages displays automatically.

Tested with Omarchy 4.0.4, Hyprland 0.56.2, and Qt 6.11.2. Omarchy installations using the older Hyprland configuration syntax are not supported.

## Install

```bash
git clone https://github.com/manateelazycat/omarchy-switch-display.git
cd omarchy-switch-display
./install.sh
```

Keep the checkout in place: the installer links it to `~/.config/omarchy/plugins/andy.switch-display`, enables the plugin, and sets up **Super+P** in `~/.config/hypr/bindings.lua`. The shortcut replaces the existing Super+P binding. The installer backs up the bindings file before editing it and validates the Hyprland configuration.

Update an existing checkout with:

```bash
git pull --ff-only
./install.sh
```

Inspect the running picker with:

```bash
omarchy-shell andy.switch-display status
```

## Switching behavior

The picker closes and releases keyboard focus before applying a layout. The backend enables and checks the target outputs before disabling other displays, stages outputs at non-overlapping positions, and waits for the actual monitor state to settle. Failed transitions attempt to restore the previous layout or recover available connected displays. Concurrent switches are rejected.

Hyprland 0.56.2 has a known mirror hotplug crash observed during development. Disconnecting an external display while mirroring can still trigger it. Use an extended login layout on that version; this plugin does not change the login layout. The [Chinese documentation](README.zh-CN.md) records the investigation and fixes.

## Validate

These checks do not change the display layout:

```bash
python3 -m unittest discover -s tests -v
omarchy plugin validate .
/usr/lib/qt6/bin/qmlformat --normalize Service.qml >/dev/null
/usr/lib/qt6/bin/qmlformat --normalize DisplayLayoutIcon.qml >/dev/null
/usr/lib/qt6/bin/qmllint DisplayLayoutIcon.qml
bash -n install.sh
```

## License

Copyright (C) 2026 Andy Stewart.

Licensed under the GNU General Public License, version 3 only (`GPL-3.0-only`). See [LICENSE](LICENSE) for the complete terms.
