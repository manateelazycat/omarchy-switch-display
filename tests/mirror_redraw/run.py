#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare real compositor pixels inside a private Wayland/PID/mount namespace."""

import argparse
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patched-bin", type=Path, required=True)
    parser.add_argument("--baseline-bin", type=Path, default=Path("/usr/bin/Hyprland"))
    parser.add_argument("--weston-root", type=Path, required=True,
                        help="Unpacked Weston package containing usr/bin/weston and usr/lib")
    parser.add_argument("--aquamarine-lib", type=Path, required=True,
                        help="Private Aquamarine build with parent protocol compatibility patch")
    parser.add_argument("--hotfix-plugin", type=Path,
                        help="Load this runtime fix only in the patched test compositor")
    parser.add_argument("--render-node", type=Path, default=Path("/dev/dri/renderD128"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    for path in [args.patched_bin, args.baseline_bin, args.weston_root / "usr/bin/weston",
                 args.aquamarine_lib / "libaquamarine.so", args.render_node]:
        if not path.exists():
            parser.error(f"Required test input does not exist: {path}")
    node = args.render_node.resolve()
    if not node.name.startswith("renderD") or not stat.S_ISCHR(node.stat().st_mode) or os.minor(node.stat().st_rdev) < 128:
        parser.error("Only a DRM render node may be exposed to this test")

    root = args.output_dir or Path(tempfile.mkdtemp(prefix="mirror-redraw-"))
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "runtime").mkdir(mode=0o700, exist_ok=True)
    (root / "home").mkdir(exist_ok=True)
    (root / "build").mkdir(exist_ok=True)
    here = Path(__file__).resolve().parent
    shutil.copy2(here / "worker.py", root / "worker.py")
    shutil.copy2(args.patched_bin, root / "build/Hyprland")
    shutil.copy2(args.baseline_bin, root / "baseline-Hyprland")
    if args.hotfix_plugin:
        shutil.copy2(args.hotfix_plugin, root / "mirror-borders.so")
        shutil.copy2(args.hotfix_plugin.parent / "build.json", root / "build.json")
        shutil.copy2(here.parent.parent / "native/load_hotfix.py", root / "load_hotfix.py")
        shutil.copy2(here.parent.parent / "apply_layout.py", root / "layout_state.py")

    flags = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "hyprland", "pixman-1", "libdrm", "pangocairo",
        "libinput", "libudev", "wayland-server", "xkbcommon"], text=True))
    with (root / "probe-build.log").open("w") as log:
        subprocess.run([os.environ.get("CXX", "c++"), "-shared", "-fPIC", "-std=c++23", "-O1",
                        str(here / "probe.cpp"), "-o", str(root / "mirror_probe.so"), *flags],
                       check=True, stdout=log, stderr=subprocess.STDOUT)

    # No desktop socket, session bus, seat device, KMS card, or inherited desktop
    # environment is reachable inside this namespace. Only the render node is bound.
    command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
               "--ro-bind", "/", "/", "--tmpfs", "/run", "--tmpfs", "/tmp", "--tmpfs", "/home",
               "--proc", "/proc", "--dev", "/dev", "--dir", "/dev/dri",
               "--dev-bind", str(args.render_node.resolve()), "/dev/dri/renderD128",
               "--bind", str(root), "/tmp/lab",
               "--ro-bind", str(args.weston_root.resolve()), "/tmp/lab/weston",
               "--ro-bind", str(args.aquamarine_lib.resolve()), "/tmp/lab/aq-build",
               "--clearenv"]
    environment = {"PATH": "/usr/bin:/bin", "HOME": "/tmp/lab/home",
                   "XDG_RUNTIME_DIR": "/tmp/lab/runtime", "XDG_CONFIG_HOME": "/tmp/lab/home/.config",
                   "XDG_CACHE_HOME": "/tmp/lab/home/.cache", "HYPRLAND_NO_SD_VARS": "1",
                   "HYPRLAND_NO_SD_NOTIFY": "1", "HYPRLAND_NO_RT": "1",
                   "HYPRLAND_NO_CRASHREPORTER": "1", "MIRROR_REDRAW_SANDBOX": "1",
                   "AQ_NO_MODIFIERS": "1", "LANG": "C.UTF-8"}
    for key, value in environment.items():
        command += ["--setenv", key, value]
    command += ["--chdir", "/tmp/lab", "/usr/bin/python3", "/tmp/lab/worker.py"]
    print(f"Isolated test output: {root}", flush=True)
    with (root / "result.txt").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    print((root / "result.txt").read_text(), end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
