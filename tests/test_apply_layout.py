# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Andy Stewart

"""Exercise asynchronous monitor transitions without touching the desktop."""

from contextlib import redirect_stdout
from copy import deepcopy
import fcntl
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apply_layout as helper


def display(name, ident, *, mirror="none", disabled=False, modes=None):
    return {
        "name": name, "id": ident, "width": 1920, "height": 1080,
        "refreshRate": 60, "x": 0, "y": 0, "scale": 1.5,
        "transform": 0, "disabled": disabled, "mirrorOf": mirror,
        "dpmsStatus": not disabled,
        "availableModes": modes or ["1920x1080@60.00Hz"],
    }


def mirrored_pair():
    return [display("eDP-1", 0), display("HDMI-A-1", 1, mirror="0",
            modes=["3840x2160@60.00Hz", "1920x1080@60.00Hz"])]


class Compositor:
    """Queue each rule for later polls and detect loss of all real outputs."""

    def __init__(self, displays):
        self.displays = deepcopy(displays)
        self.commands = []
        self.events = []
        self.pending = None
        self.delay = 3
        self.managed = False
        self.manager_polls = 0
        self.manage_at_poll = None
        self.layer_polls = 0
        self.picker_polls = 0
        self.fail_enable = None
        self.fail_disable = None
        self.apply_before_disable_error = False
        self.remove_on_disable = None
        self.drop_after_enable = None
        self.overlaps = []

    def run(self, args):
        if args[0] == "hyprmoncfg":
            self.manager_polls += 1
            if self.manager_polls == self.manage_at_poll:
                self.managed = True
            return json.dumps({"daemon": {"running": True, "unmanaged": not self.managed}})
        if args[1] == "layers":
            self.layer_polls += 1
            layers = [{"namespace": helper.PICKER_NAMESPACE}] if self.layer_polls <= self.picker_polls else []
            return json.dumps({"eDP-1": {"levels": {"3": layers}}})
        if args[1] == "monitors":
            if self.pending:
                rule, polls = self.pending
                if polls:
                    self.pending = (rule, polls - 1)
                else:
                    self.pending = None
                    self.apply(rule)
                    self.events.append(("settled", rule["output"]))
            if self.drop_after_enable and any(e == ("settled", self.drop_after_enable) for e in self.events):
                # After the rule has passed its two successful polls, emulate
                # an unplug before the source-disable guard queries again.
                self.drop_count += 1
                if self.drop_count == 3:
                    self.displays = [d for d in self.displays if d["name"] != self.drop_after_enable]
            return json.dumps(self.displays)
        if args[1] == "eval":
            self.assert_independent()
            if self.pending:
                raise AssertionError("next monitor command sent before previous rule settled")
            fields = re.findall(r'(\w+) = ("[^"]*"|true|false|-?\d+(?:\.\d+)?)', args[2])
            rule = {key: json.loads(value) for key, value in fields}
            self.commands.append(rule)
            self.events.append(("command", rule["output"]))
            if not rule["disabled"] and rule["output"] == self.fail_enable:
                self.fail_enable = None
                return "error: simulated Lua error\n"
            if rule["disabled"] and rule["output"] == self.fail_disable:
                self.fail_disable = None
                if self.apply_before_disable_error:
                    self.apply(rule)
                if self.remove_on_disable:
                    self.displays = [d for d in self.displays if d["name"] != self.remove_on_disable]
                return "error: simulated disable error\n"
            if helper.matches_rule(rule, self.displays):
                self.events.append(("settled", rule["output"]))
                return "ok\n"  # An unchanged rule has no asynchronous transition.
            self.pending = (rule, self.delay)
            return "ok\n"
        raise AssertionError(f"unexpected command: {args}")

    def apply(self, rule):
        target = next(d for d in self.displays if d["name"] == rule["output"])
        target["disabled"] = rule["disabled"]
        target["dpmsStatus"] = not rule["disabled"]
        target["mirrorOf"] = rule["mirror"] or "none"
        if not rule["disabled"]:
            match = helper.MODE.fullmatch(rule["mode"])
            target.update(width=int(match[1]), height=int(match[2]), refreshRate=float(match[3]),
                          scale=rule["scale"], transform=rule["transform"])
            target["x"], target["y"] = map(int, rule["position"].split("x"))
        self.assert_independent()
        self.record_overlaps()

    def record_overlaps(self):
        # Use independent geometry, not the helper's layout validation.
        active = [d for d in self.displays if not d["disabled"] and not helper.mirrored(d)]
        for index, left in enumerate(active):
            lw, lh = left["width"], left["height"]
            if left["transform"] % 2:
                lw, lh = lh, lw
            lw = int(lw / left["scale"] + 0.5)
            lh = int(lh / left["scale"] + 0.5)
            for right in active[index + 1:]:
                rw, rh = right["width"], right["height"]
                if right["transform"] % 2:
                    rw, rh = rh, rw
                rw = int(rw / right["scale"] + 0.5)
                rh = int(rh / right["scale"] + 0.5)
                if (left["x"] < right["x"] + rw and right["x"] < left["x"] + lw
                        and left["y"] < right["y"] + rh and right["y"] < left["y"] + lh):
                    self.overlaps.append((left["name"], right["name"]))

    def assert_independent(self):
        if not any(not d["disabled"] and not helper.mirrored(d) for d in self.displays):
            raise AssertionError("all independent outputs disappeared (FALLBACK/crash trigger)")


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)
        self.enterContext(patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.runtime.name}))
        self.enterContext(patch.object(helper, "POLL_INTERVAL", 0.001))
        self.enterContext(patch.object(helper, "SETTLE_TIMEOUT", 0.08))

    def execute(self, compositor, layout):
        with patch.object(helper, "run", side_effect=compositor.run), redirect_stdout(io.StringIO()) as output:
            helper.main(layout)
        return json.loads(output.getvalue())

    def test_mirror_to_external_waits_for_independent_target_before_disable(self):
        compositor = Compositor(mirrored_pair())
        compositor.picker_polls = 3
        self.assertTrue(self.execute(compositor, "external")["ok"])
        self.assertEqual([(r["output"], r["disabled"]) for r in compositor.commands],
                         [("HDMI-A-1", False), ("eDP-1", True), ("HDMI-A-1", False)])
        self.assertLess(compositor.events.index(("settled", "HDMI-A-1")),
                        compositor.events.index(("command", "eDP-1")))
        self.assertGreaterEqual(compositor.layer_polls, 5)
        self.assertEqual(compositor.commands[0]["mode"], "3840x2160@60")
        self.assertEqual(compositor.commands[0]["mirror"], "")
        self.assertEqual(compositor.overlaps, [])
        self.assertEqual(compositor.displays[1]["x"], 0)

    def test_mirror_available_without_a_version_query(self):
        compositor = Compositor([display("eDP-1", 0), display("HDMI-A-1", 1)])
        self.assertTrue(self.execute(compositor, "mirror")["ok"])
        self.assertEqual(helper.mirror_source(compositor.displays[1], compositor.displays), "eDP-1")
        self.assertEqual(compositor.overlaps, [])

    def test_manual_mirror_keeps_startup_configuration_unchanged(self):
        config_dir = Path(self.runtime.name) / "config"
        startup = config_dir / "hypr" / "hyprmoncfg-monitors.lua"
        startup.parent.mkdir(parents=True)
        saved = 'hl.monitor({output = "HDMI-A-1", position = "1280x0", mirror = ""})\n'
        startup.write_text(saved)
        original_stat = startup.stat()
        compositor = Compositor([display("eDP-1", 0), display("HDMI-A-1", 1)])
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_dir)}):
            for layout in ("mirror", "external", "internal", "extend", "mirror"):
                self.assertTrue(self.execute(compositor, layout)["ok"])
                self.assertEqual(startup.read_text(), saved)
                self.assertEqual(startup.stat().st_mtime_ns, original_stat.st_mtime_ns)

    def test_loading_helper_does_not_apply_a_layout(self):
        import runpy
        with patch("subprocess.run") as run:
            runpy.run_path(str(Path(helper.__file__)), run_name="plugin_import")
        run.assert_not_called()

    def test_mirror_to_internal_restores_maximum_internal_resolution(self):
        displays = mirrored_pair()
        displays[0]["availableModes"] = ["1920x1080@60.00Hz", "1920x1200@60.00Hz", "1280x720@60.00Hz"]
        compositor = Compositor(displays)
        self.assertTrue(self.execute(compositor, "internal")["ok"])
        internal = compositor.displays[0]
        self.assertEqual((internal["width"], internal["height"], internal["refreshRate"]), (1920, 1200, 60))
        self.assertEqual(internal["scale"], 1.5)
        self.assertEqual(internal["x"], 0)
        self.assertTrue(compositor.displays[1]["disabled"])
        self.assertLess(compositor.events.index(("settled", "eDP-1")),
                        compositor.events.index(("command", "HDMI-A-1")))
        self.assertEqual(compositor.overlaps, [])

    def test_external_uses_maximum_area_and_refresh_for_each_output(self):
        displays = [display("eDP-1", 0), display("HDMI-A-1", 1, disabled=True, modes=[
            "3840x2160@60.00Hz", "4096x2160@24.00Hz", "2560x1440@120.00Hz", "4096x2160@60.00Hz"
        ]), display("DP-1", 2, disabled=True, modes=[
            "5120x1440@144.00Hz", "3840x2160@30.00Hz", "3840x2160@120.00Hz"
        ])]
        displays[2].update(scale=1.25, transform=1)
        compositor = Compositor(displays)
        self.assertTrue(self.execute(compositor, "external")["ok"])
        first, second = compositor.displays[1:]
        self.assertEqual((first["width"], first["height"], first["refreshRate"]), (4096, 2160, 60))
        self.assertEqual((second["width"], second["height"], second["refreshRate"]), (3840, 2160, 120))
        self.assertEqual((second["scale"], second["transform"], second["x"]), (1.25, 1, 2731))
        self.assertTrue(compositor.displays[0]["disabled"])
        self.assertEqual(compositor.overlaps, [])

    def test_single_screen_without_advertised_modes_uses_preferred(self):
        target = display("eDP-1", 0)
        target["availableModes"] = ["invalid", "0x1080@60Hz", "1920x1200@0Hz"]
        self.assertEqual(helper.build_rules("internal", [target])[0]["mode"], "preferred")

    def test_single_screen_switch_failure_restores_original_lower_resolution(self):
        displays = mirrored_pair()
        displays[0]["availableModes"] = ["1920x1200@60.00Hz", "1920x1080@60.00Hz"]
        compositor = Compositor(displays)
        compositor.fail_disable = "HDMI-A-1"
        with self.assertRaisesRegex(RuntimeError, "已恢复原布局"):
            self.execute(compositor, "internal")
        self.assertEqual((compositor.displays[0]["width"], compositor.displays[0]["height"]), (1920, 1080))
        self.assertEqual(helper.mirror_source(compositor.displays[1], compositor.displays), "eDP-1")
        self.assertEqual(compositor.overlaps, [])

    def test_all_pairs_of_layout_transitions_keep_independent_output(self):
        for first in ("extend", "mirror", "internal", "external"):
            for second in ("extend", "mirror", "internal", "external"):
                with self.subTest(first=first, second=second):
                    compositor = Compositor(mirrored_pair())
                    self.execute(compositor, first)
                    self.assertTrue(self.execute(compositor, second)["ok"])
                    self.assertEqual(compositor.overlaps, [])

    def test_enable_error_restores_mirror_without_disabling_internal(self):
        original = mirrored_pair()
        compositor = Compositor(original)
        compositor.fail_enable = "HDMI-A-1"
        with self.assertRaisesRegex(RuntimeError, "已恢复原布局"):
            self.execute(compositor, "external")
        self.assertFalse(any(r["disabled"] for r in compositor.commands))
        self.assertFalse(compositor.displays[0]["disabled"])
        self.assertEqual(helper.mirror_source(compositor.displays[1], compositor.displays), "eDP-1")
        self.assertEqual(compositor.overlaps, [])

    def test_mixed_scale_rotated_outputs_never_overlap_during_transition(self):
        displays = [display("eDP-1", 0), display("HDMI-A-1", 1), display("DP-1", 2)]
        displays[0].update(x=-2000, y=-1000)
        displays[1].update(scale=1.25)
        displays[2].update(x=1536, scale=1, transform=1)
        compositor = Compositor(displays)
        for layout in ("external", "mirror", "extend", "internal", "extend"):
            self.assertTrue(self.execute(compositor, layout)["ok"])
            self.assertEqual(compositor.overlaps, [])

    def test_recovery_from_external_only_avoids_overlapping_live_external(self):
        compositor = Compositor([display("eDP-1", 0, disabled=True), display("HDMI-A-1", 1)])
        compositor.fail_disable = "HDMI-A-1"
        with self.assertRaisesRegex(RuntimeError, "已恢复原布局"):
            self.execute(compositor, "internal")
        self.assertEqual(compositor.overlaps, [])
        self.assertTrue(compositor.displays[0]["disabled"])
        self.assertFalse(compositor.displays[1]["disabled"])
        self.assertEqual(compositor.displays[1]["x"], 0)

    def test_recovery_includes_new_external_and_restores_internal_position(self):
        original = [display("eDP-1", 0)]
        live = deepcopy(original) + [display("HDMI-A-1", 1)]
        live[0]["x"] = 3841
        compositor = Compositor(live)
        with patch.object(helper, "run", side_effect=compositor.run):
            self.assertFalse(helper.restore(original))
        self.assertEqual(compositor.displays[0]["x"], 0)
        self.assertGreaterEqual(compositor.displays[1]["x"], 1280)
        self.assertEqual(compositor.overlaps, [])

    def test_recovery_when_all_saved_outputs_are_replaced(self):
        original = [display("eDP-1", 0)]
        compositor = Compositor([display("DP-1", 2)])
        with patch.object(helper, "run", side_effect=compositor.run):
            self.assertFalse(helper.restore(original))
        self.assertFalse(compositor.displays[0]["disabled"])
        self.assertEqual(compositor.overlaps, [])

    def test_disable_error_restores_source_before_restoring_mirror(self):
        compositor = Compositor(mirrored_pair())
        compositor.fail_disable = "eDP-1"
        compositor.apply_before_disable_error = True
        with self.assertRaisesRegex(RuntimeError, "已恢复原布局"):
            self.execute(compositor, "external")
        self.assertEqual([(r["output"], r["disabled"], r["mirror"]) for r in compositor.commands[-3:]],
                         [("eDP-1", False, ""), ("HDMI-A-1", False, "eDP-1"), ("eDP-1", False, "")])
        self.assertEqual(compositor.overlaps, [])

    def test_reapplying_current_layout_does_not_move_or_modeset_outputs(self):
        compositor = Compositor(mirrored_pair())
        self.assertTrue(self.execute(compositor, "mirror")["ok"])
        self.assertEqual(compositor.commands, [])

    def test_extending_a_mirror_keeps_matching_internal_output_untouched(self):
        compositor = Compositor(mirrored_pair())
        self.assertTrue(self.execute(compositor, "extend")["ok"])
        self.assertFalse(any(r["output"] == "eDP-1" for r in compositor.commands))
        self.assertEqual(compositor.overlaps, [])

    def test_target_removed_before_disable_keeps_internal_on(self):
        compositor = Compositor(mirrored_pair())
        compositor.drop_after_enable = "HDMI-A-1"
        compositor.drop_count = 0
        with self.assertRaisesRegex(RuntimeError, "已恢复可用屏幕"):
            self.execute(compositor, "external")
        self.assertFalse(any(r["disabled"] for r in compositor.commands))
        self.assertFalse(compositor.displays[0]["disabled"])

    def test_recovery_enables_disabled_internal_if_only_external_is_unplugged(self):
        compositor = Compositor([display("eDP-1", 0, disabled=True), display("HDMI-A-1", 1)])
        compositor.fail_disable = "HDMI-A-1"
        compositor.remove_on_disable = "HDMI-A-1"
        with self.assertRaisesRegex(RuntimeError, "已恢复可用屏幕"):
            self.execute(compositor, "internal")
        self.assertFalse(compositor.displays[0]["disabled"])

    def test_unready_external_never_disables_internal(self):
        compositor = Compositor(mirrored_pair())
        original_apply = compositor.apply
        def never_unmirror(rule):
            if rule["output"] == "HDMI-A-1" and rule["mirror"] == "":
                return
            original_apply(rule)
        compositor.apply = never_unmirror
        with self.assertRaisesRegex(RuntimeError, "已恢复原布局"):
            self.execute(compositor, "external")
        self.assertFalse(any(r["disabled"] for r in compositor.commands))

    def test_managed_daemon_rejects_before_mutation(self):
        compositor = Compositor(mirrored_pair())
        compositor.managed = True
        with self.assertRaisesRegex(RuntimeError, "自动管理"):
            self.execute(compositor, "external")
        self.assertEqual(compositor.commands, [])

    def test_picker_still_mapped_rejects_before_mutation(self):
        compositor = Compositor(mirrored_pair())
        compositor.picker_polls = 10000
        with self.assertRaisesRegex(RuntimeError, "选择器尚未关闭"):
            self.execute(compositor, "external")
        self.assertEqual(compositor.commands, [])

    def test_manager_enabled_during_switch_prevents_source_disable(self):
        compositor = Compositor(mirrored_pair())
        compositor.manage_at_poll = 2
        with self.assertRaisesRegex(RuntimeError, "已恢复原布局.*自动管理"):
            self.execute(compositor, "external")
        self.assertFalse(any(r["disabled"] for r in compositor.commands))

    def test_concurrent_switch_rejects_before_querying_compositor(self):
        with open(Path(self.runtime.name) / "andy-switch-display.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(helper, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "另一次显示切换"):
                    helper.main("external")
                run.assert_not_called()

    def test_lua_error_with_zero_exit_is_failure(self):
        with patch.object(helper, "run", return_value="error: invalid monitor rule\n"):
            with self.assertRaisesRegex(RuntimeError, "invalid monitor rule"):
                helper.apply_rule(helper.monitor_rule(display("eDP-1", 0)))

    def test_fallback_is_not_a_usable_external_display(self):
        with patch.object(helper, "run", return_value=json.dumps([display("FALLBACK", 9)])):
            self.assertEqual(helper.get_displays(), [])

    def test_exact_mirror_source_required(self):
        displays = mirrored_pair() + [display("DP-1", 2)]
        displays[1]["mirrorOf"] = "2"
        rule = helper.monitor_rule(displays[1], mirror="eDP-1")
        self.assertFalse(helper.matches_rule(rule, displays))
        rule["mirror"] = "DP-1"
        self.assertTrue(helper.matches_rule(rule, displays))

    def test_dpms_off_or_wrong_resolution_is_not_ready(self):
        target = display("HDMI-A-1", 1)
        rule = helper.monitor_rule(target)
        target["dpmsStatus"] = False
        self.assertFalse(helper.matches_rule(rule, [target]))
        target["dpmsStatus"] = True
        target["width"] = 1280
        self.assertFalse(helper.matches_rule(rule, [target]))

    def test_unsupported_mirror_timing_uses_target_mode(self):
        target = display("HDMI-A-1", 1, mirror="0", modes=["3840x2160@60.00Hz"])
        self.assertEqual(helper.get_mode(target), "3840x2160@60")

    def test_missing_external_rejects_without_commands(self):
        compositor = Compositor([display("eDP-1", 0)])
        with self.assertRaisesRegex(RuntimeError, "没有检测到外屏"):
            self.execute(compositor, "external")
        self.assertEqual(compositor.commands, [])

    def test_subprocesses_have_timeout(self):
        with patch.object(helper.subprocess, "run", side_effect=subprocess.TimeoutExpired("hyprctl", 5)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                helper.run(["hyprctl", "monitors", "all", "-j"])
            self.assertEqual(run.call_args.kwargs["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
