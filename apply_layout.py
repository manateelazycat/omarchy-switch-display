#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Andy Stewart

"""Apply monitor rules in stages, keeping an independent output available."""

import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


CONNECTOR = re.compile(r"^[A-Za-z0-9._:-]+$")
MODE = re.compile(r"^(\d+)x(\d+)@([0-9]+(?:\.[0-9]+)?)(?:Hz)?$")
POLL_INTERVAL = 0.1
SETTLE_TIMEOUT = 4
PICKER_NAMESPACE = "andy-switch-display"


def run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=5).stdout


def lua_string(value):
    return json.dumps(value)


def mirrored(display):
    return display.get("mirrorOf") not in (None, "", "none")


def mirror_source(display, displays):
    value = display.get("mirrorOf")
    if not mirrored(display):
        return ""
    for source in displays:
        if str(value) in (source["name"], str(source.get("id"))):
            return source["name"]
    raise RuntimeError("无法识别镜像来源，已取消操作")


def get_displays():
    data = json.loads(run(["hyprctl", "monitors", "all", "-j"]))
    if not isinstance(data, list) or any(not isinstance(d, dict) for d in data):
        raise RuntimeError("Hyprland 返回了无效的显示器状态")
    return [d for d in data if d.get("name") and d["name"] != "FALLBACK"
            and (d.get("availableModes") or not d.get("disabled"))]


def get_mode(display, *, max_resolution=False):
    available = [MODE.fullmatch(str(candidate)) for candidate in display.get("availableModes", [])]
    available = [match for match in available if match and int(match[1]) > 0 and int(match[2]) > 0
                 and math.isfinite(float(match[3])) and float(match[3]) > 0]
    width, height, rate = display.get("width"), display.get("height"), display.get("refreshRate")
    if not max_resolution and not display.get("disabled") and width and height and rate:
        # Reuse a mirrored output's reported timing only when the target
        # advertises it, avoiding an unnecessary switch to 4K.
        supported = any(int(m[1]) == int(width) and int(m[2]) == int(height)
                        and abs(float(m[3]) - float(rate)) < 0.1 for m in available)
        if not mirrored(display) or supported:
            return f"{int(width)}x{int(height)}@{float(rate):g}"
    if available:
        # Single-screen layouts must not inherit the lower mirror timing.
        # Prefer the largest pixel area, then the highest refresh at that size.
        match = available[0]
        if max_resolution:
            match = max(available, key=lambda m: (
                int(m[1]) * int(m[2]), int(m[1]), int(m[2]), float(m[3])))
        return f"{match[1]}x{match[2]}@{float(match[3]):g}"
    return "preferred"


def logical_width(display, mode):
    match = MODE.fullmatch(mode)
    width = float(match[1]) if match else float(display.get("width") or 1920)
    if int(display.get("transform") or 0) % 2:
        width = float(match[2]) if match else float(display.get("height") or 1080)
    return max(1, math.floor(width / float(display.get("scale") or 1) + 0.5))


def internal(display):
    description = str(display.get("description", "")).lower()
    return bool(re.match(r"^(eDP|LVDS|DSI)(-|$)", display["name"], re.I)) or "built-in" in description or "internal" in description


def current_layout(displays):
    enabled = [d for d in displays if not d.get("disabled") and d.get("width") and d.get("height")]
    if not enabled:
        raise RuntimeError("没有检测到已启用的显示器")
    sources = [d for d in enabled if not mirrored(d)]
    mirrors = [d for d in enabled if mirrored(d)]
    mirror_sources = [mirror_source(d, enabled) for d in mirrors]
    if len(sources) == 1 and mirrors and all(name == sources[0]["name"] for name in mirror_sources):
        return "mirror"
    if all(internal(d) for d in enabled):
        return "internal"
    if not any(internal(d) for d in enabled) and (len(enabled) == 1 or any(internal(d) for d in displays)):
        return "external"
    return "extend"


def monitor_rule(display, *, position=None, mirror="", disabled=False, max_resolution=False):
    if disabled:
        return {"output": display["name"], "disabled": True, "mirror": ""}
    return {
        "output": display["name"], "disabled": False,
        "mode": get_mode(display, max_resolution=max_resolution),
        "position": position or f"{int(display.get('x') or 0)}x{int(display.get('y') or 0)}",
        "scale": float(display.get("scale") or 1),
        "transform": int(display.get("transform") or 0), "mirror": mirror,
    }


def build_rules(layout, displays):
    if layout not in ("extend", "mirror", "internal", "external"):
        raise RuntimeError("未知的显示布局")
    if not displays:
        raise RuntimeError("没有检测到可用显示器")
    for display in displays:
        if not CONNECTOR.fullmatch(str(display["name"])):
            raise RuntimeError("显示器接口名格式不受支持，已取消操作")
        scale = float(display.get("scale") or 1)
        if not math.isfinite(scale) or scale <= 0 or not 0 <= int(display.get("transform") or 0) <= 7:
            raise RuntimeError("显示器缩放或旋转信息无效，已取消操作")

    builtins = [d for d in displays if internal(d)]
    externals = [d for d in displays if not internal(d)]
    enabled = builtins if layout == "internal" else externals if layout == "external" else displays
    if not enabled:
        raise RuntimeError("没有检测到内屏" if layout == "internal" else "没有检测到外屏")
    source = (builtins or displays)[0]
    rules, position = [], 0
    for display in displays:
        if display not in enabled:
            rules.append(monitor_rule(display, disabled=True))
            continue
        mirror = source["name"] if layout == "mirror" and display != source else ""
        rule = monitor_rule(display, position=f"{position}x0", mirror=mirror,
                            max_resolution=layout in ("internal", "external"))
        rules.append(rule)
        if layout in ("extend", "external"):
            position += logical_width(display, rule["mode"])
    return rules


def matches_rule(rule, displays):
    display = next((d for d in displays if d["name"] == rule["output"]), None)
    if rule["disabled"]:
        return display is None or bool(display.get("disabled"))
    if display is None or display.get("disabled") or display.get("dpmsStatus") is False:
        return False
    if not display.get("width") or not display.get("height"):
        return False
    try:
        if mirror_source(display, displays) != rule["mirror"]:
            return False
    except RuntimeError:
        return False
    if rule["mirror"]:
        return True  # Mirroring uses the source desktop instead of an independent position.
    mode = MODE.fullmatch(rule["mode"])
    if mode and (int(display["width"]) != int(mode[1]) or int(display["height"]) != int(mode[2])
                 or abs(float(display.get("refreshRate") or 0) - float(mode[3])) > 0.15):
        return False
    return (f"{int(display.get('x') or 0)}x{int(display.get('y') or 0)}" == rule["position"]
            and abs(float(display.get("scale") or 1) - rule["scale"]) < 0.0001
            and int(display.get("transform") or 0) == rule["transform"])


def wait_for(predicate, message):
    deadline = time.monotonic() + SETTLE_TIMEOUT
    consecutive = 0
    while time.monotonic() < deadline:
        consecutive = consecutive + 1 if predicate() else 0
        if consecutive >= 2:
            return
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(message)


def wait_for_rules(rules):
    def ready():
        displays = get_displays()
        return all(matches_rule(rule, displays) for rule in rules)
    wait_for(ready, "目标屏幕未就绪，已停止后续关闭屏幕操作")


def wait_for_picker_closed():
    def closed():
        layers = json.loads(run(["hyprctl", "layers", "-j"]))
        return not any(layer.get("namespace") == PICKER_NAMESPACE
                       for monitor in layers.values()
                       for level in monitor.get("levels", {}).values() for layer in level)
    wait_for(closed, "显示选择器尚未关闭，已取消切换")


def check_manager():
    try:
        manager = json.loads(run(["hyprmoncfg", "status", "--json"]))
    except FileNotFoundError:
        return
    except (subprocess.SubprocessError, ValueError) as error:
        raise RuntimeError("无法确认 hyprmoncfg 的管理状态，已取消切换") from error
    if not isinstance(manager, dict) or not isinstance(manager.get("daemon", {}), dict):
        raise RuntimeError("hyprmoncfg 返回了无效的管理状态，已取消切换")
    daemon = manager.get("daemon", {})
    if daemon.get("running") and not daemon.get("unmanaged"):
        raise RuntimeError("hyprmoncfgd 正在自动管理显示器，请先切换为手动管理后再使用此选择器")


def apply_rule(rule):
    fields = ", ".join(f"{key} = {str(value).lower() if isinstance(value, bool) else lua_string(value)}"
                       for key, value in rule.items())
    output = run(["hyprctl", "eval", f"hl.monitor({{ {fields} }})"])
    # hyprctl can exit zero while reporting a Lua error on stdout.
    if output.strip() != "ok":
        raise RuntimeError(output.strip() or "Hyprland 未确认显示器配置")


def apply_rules(rules):
    independent = [rule for rule in rules if not rule["disabled"] and not rule["mirror"]]
    if not independent:
        raise RuntimeError("布局缺少独立显示器，已取消操作")
    completed = {}
    # Reserve space beyond both the live and final layouts. A newly enabled
    # or unmirrored target must not share 0x0 with the still-active old output.
    final_right = max(int(r["position"].split("x")[0]) + logical_width(r, r["mode"])
                      for r in independent)
    # Never submit disable rules in the same eval as unmirroring. Hyprland
    # processes monitor changes asynchronously: wait for real output state.
    for rule in independent:
        live = get_displays()
        if matches_rule(rule, live):
            completed[rule["output"]] = rule
            continue
        live_right = max((int(d.get("x") or 0) + logical_width(d, get_mode(d))
                          for d in live if not d.get("disabled")), default=0)
        staged = {**rule, "position": f"{max(final_right, live_right) + 1}x0"}
        apply_rule(staged)
        completed[rule["output"]] = staged
        wait_for_rules(list(completed.values()))
    for rule in [r for r in rules if not r["disabled"] and r["mirror"]]:
        if not matches_rule(rule, get_displays()):
            apply_rule(rule)
        completed[rule["output"]] = rule
        wait_for_rules(list(completed.values()))
    for rule in [r for r in rules if r["disabled"]]:
        check_manager()
        wait_for_rules(list(completed.values()))
        if not matches_rule(rule, get_displays()):
            apply_rule(rule)
        completed[rule["output"]] = rule
        wait_for_rules(list(completed.values()))
    displays = get_displays()
    expected = {r["output"] for r in rules if not r["disabled"]}
    if {d["name"] for d in displays if not d.get("disabled")} != expected:
        raise RuntimeError("显示器连接状态发生变化，已取消切换")
    # All obsolete outputs are off or mirrored now. Compact the surviving
    # independent outputs into their final, non-overlapping positions.
    for rule in independent:
        if completed[rule["output"]] != rule:
            apply_rule(rule)
        completed[rule["output"]] = rule
        wait_for_rules(list(completed.values()))


def restore(displays):
    live = get_displays()
    connected = {d["name"] for d in live}
    saved_names = {d["name"] for d in displays}
    exact = connected == {d["name"] for d in displays}
    rules = [monitor_rule(d, mirror=mirror_source(d, displays), disabled=bool(d.get("disabled")))
             for d in displays if d["name"] in connected]
    # If a mirror source was unplugged, recover its surviving target as an
    # independent output instead of restoring a dangling mirror relationship.
    for rule in rules:
        if rule.get("mirror") not in connected:
            if rule.get("mirror"):
                exact = False
            rule["mirror"] = ""
    # Hotplug can add an output after the snapshot. Include it in recovery
    # instead of rejecting the new topology and leaving saved outputs staged.
    right = max((int(r["position"].split("x")[0]) + logical_width(r, r["mode"])
                 for r in rules if not r["disabled"] and not r["mirror"]), default=0)
    for display in live:
        if display["name"] in saved_names:
            continue
        mirror = mirror_source(display, live)
        rule = monitor_rule(display, mirror=mirror, disabled=bool(display.get("disabled")))
        if not rule["disabled"] and not mirror:
            rule["position"] = f"{right + 1}x0"
            right += 1 + logical_width(rule, rule["mode"])
        rules.append(rule)
    if rules and not any(not r["disabled"] and not r["mirror"] for r in rules):
        survivor = next(d for d in live if d["name"] in connected)
        rules = [monitor_rule(survivor) if r["output"] == survivor["name"] else r for r in rules]
        exact = False
    apply_rules(rules)
    return exact


def main(layout):
    # Layouts are session-only. Keep login monitor files untouched so a
    # manually selected mirror is never restored automatically at startup.
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    with (runtime_dir / "andy-switch-display.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("另一次显示切换正在进行，请稍后重试") from error
        displays = get_displays()
        rules = build_rules(layout, displays)
        check_manager()
        wait_for_picker_closed()
        # Validate the snapshot's mirror relationships before the first write.
        for display in displays:
            mirror_source(display, displays)
        try:
            apply_rules(rules)
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
            try:
                exact = restore(displays)
            except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as recovery:
                raise RuntimeError(f"切换失败：{error}；恢复原布局失败：{recovery}") from error
            recovery = "已恢复原布局" if exact else "已恢复可用屏幕"
            raise RuntimeError(f"切换失败，{recovery}：{error}") from error
        print(json.dumps({"ok": True, "message": "显示布局已切换"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--capabilities"]:
            print(json.dumps({"mirrorAllowed": True, "mirrorReason": ""}))
        elif sys.argv[1:] == ["--current-layout"]:
            print(json.dumps({"ok": True, "layout": current_layout(get_displays())}))
        else:
            main(sys.argv[1] if len(sys.argv) == 2 else "")
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        print(json.dumps({"ok": False, "message": message or "切换显示布局失败"}, ensure_ascii=False))
        sys.exit(1)
