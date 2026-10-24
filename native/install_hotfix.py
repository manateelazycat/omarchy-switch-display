#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build or install the version-specific mirror border fix without restarting Hyprland."""

import argparse
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def private_build_directory(path, *, create=False):
    """Walk without following links; pin a private, current-user build directory."""
    path = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path.anchor, flags)
    try:
        for index, part in enumerate(path.parts):
            if index:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create or index != len(path.parts) - 1:
                        raise
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if index == len(path.parts) - 1:
                if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                    raise ValueError("Build directory must be owned by the current user with mode 0700; "
                                     "create a fresh directory with mktemp -d")
            elif (info.st_uid not in (0, os.geteuid())
                  or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)):
                # A root/current-user-owned sticky directory such as /tmp is
                # safe: other users cannot rename our owned child within it.
                raise ValueError(f"Untrusted or writable build directory ancestor: {path.parts[:index + 1]}")
        yield path, descriptor
    finally:
        os.close(descriptor)


def read_build_file(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or info.st_nlink != 1):
            raise ValueError(f"Unsafe build file: {name}; expected an owned regular file "
                             "with one link and no group/other write permission")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def compile_hotfix(build, directory, source, version):
    flags = shlex.split(run("pkg-config", "--cflags", "hyprland", "pixman-1", "libdrm", "pangocairo",
                           "libinput", "libudev", "wayland-server", "xkbcommon"))
    # Never let the compiler or metadata writer follow an existing output link.
    with tempfile.TemporaryDirectory(prefix=".compile-", dir=build) as staging:
        staging = Path(staging)
        binary = staging / "mirror-borders.so"
        subprocess.run(["c++", "-shared", "-fPIC", "-std=c++23", "-O2", "-Wall", "-Wextra",
                        str(source), "-o", str(binary), *flags], check=True)
        binary.chmod(0o600)
        metadata = dict(abiHash=version["abiHash"], commit=version["commit"],
                        source_sha256=digest(source), binary_sha256=digest(binary))
        (staging / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (staging / "build.json").chmod(0o600)
        for name in ("mirror-borders.so", "build.json"):
            os.replace(staging / name, name, dst_dir_fd=directory)


def verified_build_files(directory, source, version):
    files = {name: read_build_file(directory, name) for name in ("mirror-borders.so", "build.json")}
    metadata = json.loads(files["build.json"])
    if (not isinstance(metadata, dict) or metadata.get("abiHash") != version["abiHash"]
            or metadata.get("commit") != version["commit"]
            or metadata.get("source_sha256") != digest(source)
            or metadata.get("binary_sha256") != hashlib.sha256(files["mirror-borders.so"]).hexdigest()):
        raise ValueError("Build metadata does not match the source, binary, or running compositor")
    # Installation uses these exact checked bytes, never reopens the build paths.
    return files


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
    try:
        with private_build_directory(build, create=not args.from_build) as (build, directory):
            if not args.from_build:
                compile_hotfix(build, directory, source, version)
            files = verified_build_files(directory, source, version)
    except (OSError, ValueError) as error:
        parser.error(str(error))
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
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    files.update({"load_hotfix.py": (here / "load_hotfix.py").read_bytes(),
                  "layout_state.py": (here.parent / "apply_layout.py").read_bytes()})
    for name, content in files.items():
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".install-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
                stream.close()
                temporary.replace(destination / name)
            finally:
                temporary.unlink(missing_ok=True)
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
