#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Andy Stewart

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/andy.switch-display"

if [[ -e "$plugin_dir" && ! -L "$plugin_dir" ]]; then
  echo "插件目录已存在，无法建立项目链接：$plugin_dir" >&2
  exit 1
fi
if [[ -L "$plugin_dir" && "$(readlink -f -- "$plugin_dir")" != "$project_dir" ]]; then
  echo "插件目录已经指向其他位置：$plugin_dir" >&2
  exit 1
fi

mkdir -p -- "$(dirname -- "$plugin_dir")"
ln -sfn -- "$project_dir" "$plugin_dir"
omarchy plugin validate "$project_dir"
if ! omarchy plugin enable andy.switch-display; then
  echo "提示：通过 Omarchy Shell IPC 启用失败，将插件加入 shell.json 以便下次启动时加载。" >&2
  shell_config="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/shell.json"
  if [[ -f "$shell_config" ]]; then
    cp -- "$shell_config" "$shell_config.bak.switch-display-enable.$(date +%Y%m%d%H%M%S)"
    python3 - "$shell_config" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
config = json.loads(path.read_text())
plugins = config.setdefault("plugins", [])
if not any(isinstance(plugin, dict) and plugin.get("id") == "andy.switch-display" for plugin in plugins):
    plugins.append({"id": "andy.switch-display"})
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
PY
  fi
fi
export OMARCHY_SHELL_IPC_TIMEOUT=20s
if ! omarchy-shell shell rescanPlugins; then
  echo "提示：Omarchy Shell 当前未运行，插件将在 Shell 启动后加载。" >&2
fi
bindings="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/bindings.lua"
if [[ -f "$bindings" ]]; then
  cp -- "$bindings" "$bindings.bak.switch-display.$(date +%Y%m%d%H%M%S)"
  python3 - "$bindings" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old_unbind = 'hl.unbind("SUPER + P")'
old_better = 'o.bind("SUPER + P", "Better Displays Pro", "omarchy shell omarchy.monitor toggle")'
new_unbind = 'hl.unbind("SUPER + P")'
new_bind = 'hl.bind("SUPER + P", hl.dsp.global("quickshell:andySwitchDisplayNext"), { repeating = true, description = "Switch Display preview" })'
lines = text.splitlines()
lines = [line for line in lines if line.strip() not in (
    old_unbind,
    old_better,
    new_unbind,
    new_bind,
    'o.bind("SUPER + P", "Switch Display", "omarchy shell andy.switch-display toggle")',
    '-- Switch display layouts with the standalone picker.',
    '-- Replace the default Pseudo window shortcut with Better Displays Pro.',
)]
while lines and not lines[-1].strip():
    lines.pop()
lines.extend(["", "-- Switch display layouts with the standalone picker.", new_unbind, new_bind, ""])
path.write_text("\n".join(lines))
PY
  if hyprctl reload; then
    errors="$(hyprctl configerrors)"
    if [[ -n "$errors" && "$errors" != "no errors" ]]; then
      printf '%s\n' "$errors" >&2
      exit 1
    fi
  else
    echo "提示：Hyprland 当前未运行，快捷键配置已写入，之后启动 Hyprland 时生效。" >&2
  fi
fi
echo "Switch Display 已安装。Super+P 可打开显示布局选择器。"
