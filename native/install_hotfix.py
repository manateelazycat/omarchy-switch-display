#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build or install the version-specific mirror border fix without restarting Hyprland."""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", type=Path, help="Build here without loading or installing")
    parser.add_argument("--from-build", type=Path, help="Install a previously built and tested directory")
    args = parser.parse_args()
    if args.build_only and args.from_build:
        parser.error("--build-only and --from-build are mutually exclusive")
    here = Path(__file__).resolve().parent
    source = here / "mirror_borders.cpp"
    version = json.loads(run("hyprctl", "-j", "version"))
    if version.get("commit") != "efb50993780079460b0cbed1363e2166a2de1d9f":
        parser.error("This fix targets Hyprland 0.56.2; the running version differs")
    build = args.from_build or args.build_only or Path(tempfile.mkdtemp(prefix="mirror-borders-build-"))
    build = build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    if not args.from_build:
        flags = shlex.split(run("pkg-config", "--cflags", "hyprland", "pixman-1", "libdrm", "pangocairo",
                                "libinput", "libudev", "wayland-server", "xkbcommon"))
        subprocess.run(["c++", "-shared", "-fPIC", "-std=c++23", "-O2", "-Wall", "-Wextra",
                        str(source), "-o", str(build / "mirror-borders.so"), *flags], check=True)
        metadata = dict(abiHash=version["abiHash"], commit=version["commit"],
                        source_sha256=digest(source), binary_sha256=digest(build / "mirror-borders.so"))
        (build / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    metadata = json.loads((build / "build.json").read_text())
    if (metadata["abiHash"] != version["abiHash"] or metadata["source_sha256"] != digest(source)
            or metadata["binary_sha256"] != digest(build / "mirror-borders.so")):
        parser.error("Build metadata does not match the source, binary, or running compositor")
    if args.build_only:
        print(build)
        return

    home = Path.home()
    destination = home / ".local/share/omarchy-switch-display/mirror-borders"
    unit = home / ".config/systemd/user/omarchy-mirror-borders.service"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = home / ".local/state/omarchy-switch-display" / ("native-install-" + stamp)
    backup.mkdir(parents=True)
    if destination.exists():
        shutil.copytree(destination, backup / "previous-runtime")
    if unit.exists():
        shutil.copy2(unit, backup / unit.name)
    destination.mkdir(parents=True, exist_ok=True)
    for name, source_file in [("mirror-borders.so", build / "mirror-borders.so"),
                              ("build.json", build / "build.json"),
                              ("load_hotfix.py", here / "load_hotfix.py"),
                              ("layout_state.py", here.parent / "apply_layout.py")]:
        temporary = destination / (name + ".new")
        shutil.copy2(source_file, temporary)
        temporary.replace(destination / name)
    unit.parent.mkdir(parents=True, exist_ok=True)
    executable = str(destination / "load_hotfix.py").replace("%", "%%")
    unit.write_text(f'''[Unit]
Description=Keep Hyprland mirror borders black on reconnect
After=graphical-session-pre.target
PartOf=graphical-session.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 "{executable}"
RemainAfterExit=yes

[Install]
WantedBy=graphical-session.target
''')
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "--now", unit.name)
    # Also runs when the service was already active, without registering twice.
    print(run("/usr/bin/python3", str(destination / "load_hotfix.py")))
    print("Installed:", destination)
    print("Backup:", backup)


if __name__ == "__main__":
    main()
