# SPDX-License-Identifier: GPL-3.0-only
"""Reject untrusted native builds without compiling or touching the desktop."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native import install_hotfix as installer


class NativeInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build = self.root / "build"
        self.build.mkdir(mode=0o700)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.source = Path(installer.__file__).with_name("mirror_borders.cpp")
        self.binary = b"original tested native plugin"
        self.version = {"commit": "efb50993780079460b0cbed1363e2166a2de1d9f", "abiHash": "test-abi"}
        self.write_build()

    def write_build(self, binary=None):
        binary = self.binary if binary is None else binary
        metadata = {**self.version, "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                    "binary_sha256": hashlib.sha256(binary).hexdigest()}
        (self.build / "mirror-borders.so").write_bytes(binary)
        (self.build / "build.json").write_text(json.dumps(metadata))
        for name in ("mirror-borders.so", "build.json"):
            (self.build / name).chmod(0o600)

    def read_build(self):
        with installer.private_build_directory(self.build) as (_, descriptor):
            return installer.verified_build_files(descriptor, self.source, self.version)

    def fake_run(self, *args):
        if args == ("hyprctl", "-j", "version"):
            return json.dumps(self.version)
        if args[0] == "pkg-config":
            return ""
        return "ok"

    def fake_compile(self, args, **kwargs):
        self.assertEqual(args[0], "c++")
        Path(args[args.index("-o") + 1]).write_bytes(self.binary)

    def invoke(self, *args, home=None):
        with (patch.object(sys, "argv", ["install_hotfix.py", *map(str, args)]),
              patch.object(installer, "run", side_effect=self.fake_run) as run,
              patch.object(installer.subprocess, "run", side_effect=self.fake_compile) as compile_run,
              patch.object(installer.Path, "home", side_effect=home or (lambda: self.home)),
              redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())):
            installer.main()
        return run, compile_run

    def test_owned_private_build_is_accepted(self):
        self.assertEqual(self.read_build()["mirror-borders.so"], self.binary)

    def test_nonprivate_build_directory_is_rejected_before_install(self):
        for mode in (0o755, 0o770, 0o777, 0o720, 0o702):
            with self.subTest(mode=oct(mode)):
                self.build.chmod(mode)
                with self.assertRaises(SystemExit) as error:
                    self.invoke("--from-build", self.build)
                self.assertEqual(error.exception.code, 2)
                self.assertFalse((self.home / ".local").exists())
        self.build.chmod(0o700)

    def test_foreign_owned_directory_and_ancestor_are_rejected(self):
        real_fstat = os.fstat
        for path in (self.build, self.root):
            inode = path.stat().st_ino

            def foreign_owner(descriptor):
                info = real_fstat(descriptor)
                if info.st_ino == inode:
                    return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=info.st_mode)
                return info

            with self.subTest(path=path), patch.object(installer.os, "fstat", side_effect=foreign_owner):
                with self.assertRaises(ValueError):
                    self.read_build()

    def test_directory_and_ancestor_symlinks_are_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.build, target_is_directory=True)
        parent_link = self.root / "parent-link"
        parent_link.symlink_to(self.root, target_is_directory=True)
        for path in (link, parent_link / "build"):
            with self.subTest(path=path), self.assertRaises(OSError):
                with installer.private_build_directory(path):
                    self.fail("followed an untrusted directory symlink")

    def test_writable_nonsticky_ancestor_is_rejected(self):
        self.root.chmod(0o777)
        with self.assertRaises(ValueError):
            self.read_build()

    def test_trusted_sticky_shared_ancestor_is_accepted(self):
        self.root.chmod(0o1777)
        self.assertEqual(self.read_build()["mirror-borders.so"], self.binary)

    def test_missing_build_directory_is_not_created_when_installing(self):
        path = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            with installer.private_build_directory(path):
                self.fail("installed from a missing build")
        self.assertFalse(path.exists())

    def test_symlink_hardlink_and_writable_artifacts_are_rejected(self):
        for name in ("mirror-borders.so", "build.json"):
            path = self.build / name
            original = path.read_bytes()
            target = self.root / (name + ".outside")
            target.write_bytes(original)
            target.chmod(0o600)
            for kind in ("symlink", "hardlink", "group-writable", "world-writable"):
                with self.subTest(file=name, kind=kind):
                    path.unlink()
                    if kind == "symlink":
                        path.symlink_to(target)
                    elif kind == "hardlink":
                        os.link(target, path)
                    else:
                        path.write_bytes(original)
                        path.chmod(0o620 if kind == "group-writable" else 0o602)
                    with self.assertRaises((OSError, ValueError)):
                        self.read_build()
            path.unlink()
            path.write_bytes(original)
            path.chmod(0o600)

    def test_foreign_owned_artifact_is_rejected(self):
        real_fstat = os.fstat
        for name in ("mirror-borders.so", "build.json"):
            inode = (self.build / name).stat().st_ino

            def foreign_owner(descriptor):
                info = real_fstat(descriptor)
                if info.st_ino == inode:
                    return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=info.st_mode, st_nlink=1)
                return info

            with self.subTest(file=name), patch.object(installer.os, "fstat", side_effect=foreign_owner):
                with self.assertRaises(ValueError):
                    self.read_build()

    def test_fifo_and_directory_are_rejected_as_artifacts(self):
        path = self.build / "mirror-borders.so"
        path.unlink()
        os.mkfifo(path, mode=0o600)
        with self.assertRaises(ValueError):
            self.read_build()
        path.unlink()
        path.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            self.read_build()

    def test_modified_binary_is_rejected(self):
        (self.build / "mirror-borders.so").write_bytes(b"replaced binary")
        with self.assertRaises(ValueError):
            self.read_build()

    def test_mismatched_or_invalid_metadata_is_rejected(self):
        path = self.build / "build.json"
        original = path.read_text()
        for field in ("abiHash", "commit", "source_sha256", "binary_sha256"):
            for action in ("change", "remove"):
                metadata = json.loads(original)
                if action == "change":
                    metadata[field] = "wrong"
                else:
                    metadata.pop(field)
                with self.subTest(field=field, action=action), self.assertRaises(ValueError):
                    path.write_text(json.dumps(metadata))
                    self.read_build()
        for content in ("{broken-json", "[]", "null"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                path.write_text(content)
                self.read_build()

    def test_replaced_binary_and_matching_metadata_in_shared_directory_are_rejected(self):
        self.write_build(b"attacker plugin with matching checksum")
        self.build.chmod(0o777)
        with self.assertRaises(ValueError):
            self.read_build()

    def test_build_only_creates_private_directory_and_never_installs(self):
        build = self.root / "fresh-build"
        run, compile_run = self.invoke("--build-only", build)
        self.assertEqual(stat.S_IMODE(build.stat().st_mode), 0o700)
        self.assertEqual((build / "mirror-borders.so").read_bytes(), self.binary)
        compile_run.assert_called_once()
        self.assertEqual([call.args[0] for call in run.call_args_list], ["hyprctl", "pkg-config"])
        self.assertFalse((self.home / ".local").exists())

    def test_compiler_cannot_follow_preexisting_output_links(self):
        target = self.root / "do-not-overwrite"
        target.write_bytes(b"unrelated file")
        for name in ("mirror-borders.so", "build.json"):
            (self.build / name).unlink()
            (self.build / name).symlink_to(target)
        self.invoke("--build-only", self.build)
        self.assertEqual(target.read_bytes(), b"unrelated file")
        self.assertEqual(self.read_build()["mirror-borders.so"], self.binary)
        self.assertFalse(list(self.build.glob(".compile-*")))

    def test_default_build_uses_random_private_directory(self):
        with patch.object(installer.tempfile, "tempdir", str(self.root)):
            self.invoke()
        builds = list(self.root.glob("mirror-borders-build-*"))
        self.assertEqual(len(builds), 1)
        self.assertEqual(stat.S_IMODE(builds[0].stat().st_mode), 0o700)
        destination = self.home / ".local/share/omarchy-switch-display/mirror-borders"
        self.assertEqual((destination / "mirror-borders.so").read_bytes(), self.binary)

    def test_install_uses_verified_snapshot_even_if_build_is_replaced(self):
        original_metadata = (self.build / "build.json").read_bytes()

        def replace_after_verification():
            self.write_build(b"replacement after verification")
            return self.home

        run, compile_run = self.invoke("--from-build", self.build, home=replace_after_verification)
        destination = self.home / ".local/share/omarchy-switch-display/mirror-borders"
        self.assertEqual((destination / "mirror-borders.so").read_bytes(), self.binary)
        self.assertEqual((destination / "build.json").read_bytes(), original_metadata)
        self.assertEqual((destination / "load_hotfix.py").read_bytes(),
                         Path(installer.__file__).with_name("load_hotfix.py").read_bytes())
        self.assertTrue((destination / "layout_state.py").is_file())
        self.assertFalse(list(destination.glob(".install-*")))
        self.assertTrue((self.home / ".config/systemd/user/omarchy-mirror-borders.service").is_file())
        compile_run.assert_not_called()
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         ["hyprctl", "systemctl", "systemctl", "/usr/bin/python3"])


if __name__ == "__main__":
    unittest.main()
