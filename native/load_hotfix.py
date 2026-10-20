#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Load the matching mirror hotfix once in the current Hyprland session."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def hyprctl(*arguments):
    result = subprocess.run(["hyprctl", *arguments], text=True, capture_output=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "hyprctl failed")
    return result.stdout.strip()


def restore_layout(monitors):
    from layout_state import apply_rule, get_displays, mirrored, monitor_rule, restore, wait_for_rules
    # Pin automatic positions before staging another output. Otherwise moving
    # one monitor can rearrange an unchanged auto-positioned monitor and make
    # the restoration helper wait for a position that no longer holds.
    pinned = [monitor_rule(m) for m in get_displays() if not m.get("disabled") and not mirrored(m)]
    for rule in pinned:
        apply_rule(rule)
    wait_for_rules(pinned)
    return restore(monitors)


def main():
    root = Path(__file__).resolve().parent
    metadata = json.loads((root / "build.json").read_text())
    # UWSM exports the session environment before graphical-session.target.
    # Allow the compositor IPC socket a short interval to become available.
    for attempt in range(20):
        try:
            version = json.loads(hyprctl("-j", "version"))
            break
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            if attempt == 19:
                raise
            time.sleep(0.25)
    if version.get("abiHash") != metadata["abiHash"]:
        print("mirror-borders: skipped because the running Hyprland ABI changed; rebuild before loading")
        return
    plugins = json.loads(hyprctl("-j", "plugin", "list"))
    if any(plugin.get("name") == "mirror-borders" for plugin in plugins):
        print("mirror-borders: already loaded")
        return
    # Hyprland reloads the user's config after loading a native plugin, which
    # otherwise replaces session-only layouts with the saved login layout.
    monitors = json.loads(hyprctl("monitors", "all", "-j"))
    event_path = (Path(os.environ["XDG_RUNTIME_DIR"]) / "hypr" /
                  os.environ["HYPRLAND_INSTANCE_SIGNATURE"] / ".socket2.sock")
    with socket.socket(socket.AF_UNIX) as events:
        events.settimeout(5)
        events.connect(str(event_path))
        result = hyprctl("plugin", "load", str(root / "mirror-borders.so"))
        if result != "ok":
            raise RuntimeError(result)
        try:
            deadline = time.monotonic() + 5
            received = b""
            while b"configreloaded>>" not in received:
                events.settimeout(max(0.01, deadline - time.monotonic()))
                packet = events.recv(65536)
                if not packet:
                    raise RuntimeError("Hyprland event stream closed during plugin load")
                received += packet
                if time.monotonic() >= deadline:
                    raise TimeoutError("Hyprland did not report its config reload")
        finally:
            if not restore_layout(monitors):
                print("mirror-borders: monitor topology changed during loading; restored available outputs")
    print("mirror-borders: loaded")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"mirror-borders: {error}", file=sys.stderr)
        raise SystemExit(1)
