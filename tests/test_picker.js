// SPDX-License-Identifier: GPL-3.0-only
// Exercise the actual QML controller functions with asynchronous process replies.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../Service.qml"), "utf8");

function picker() {
  const root = { helperPath: "/test/apply_layout.py" };
  const reads = [];
  const applied = [];
  const currentLayoutProcess = {
    generation: -1,
    _running: false,
    get running() { return this._running; },
    set running(value) {
      this._running = value;
      if (value) reads.push(this.generation);
    },
  };
  const applyProcess = {
    command: [],
    set running(value) { if (value) applied.push(this.command[2]); },
  };
  const context = vm.createContext({ root, currentLayoutProcess, applyProcess });
  for (const match of source.matchAll(/^  property (?:bool|int|string) (\w+): (.+)$/gm))
    vm.runInContext(`root.${match[1]} = ${match[2]}`, context);
  const layouts = source.match(/readonly property var layouts: (\[[\s\S]*?\n  \])/)[1];
  vm.runInContext(`root.layouts = ${layouts}`, context);
  for (const match of source.matchAll(/^  function (\w+)\([^)]*\) \{[\s\S]*?^  \}/gm)) {
    vm.runInContext(match[0], context);
    root[match[1]] = (...args) => context[match[1]](...args);
  }
  function reply(layout, exitCode = 0, output = JSON.stringify({ ok: true, layout })) {
    const generation = currentLayoutProcess.generation;
    currentLayoutProcess.running = false;
    root.receiveCurrentLayout(generation, exitCode, output, "");
  }
  return { root, reads, applied, reply, selected: () => root.layouts[root.selectedIndex]?.id };
}

test("opening highlights the live mode instead of defaulting to extend", () => {
  for (const layout of ["extend", "mirror", "internal", "external"]) {
    const p = picker();
    p.root.nextPreview();
    assert.equal(p.root.selectedIndex, -1);
    assert.equal(p.reads.length, 1);
    p.reply(layout);
    assert.equal(p.selected(), layout);
    assert.equal(p.root.opened, true);
    assert.deepEqual(p.applied, []);
  }
});

test("opening again reads a mode changed outside the picker", () => {
  const p = picker();
  p.root.nextPreview();
  p.reply("extend");
  p.root.close();
  p.root.nextPreview();
  p.reply("mirror");
  assert.equal(p.selected(), "mirror");
  assert.equal(p.reads.length, 2);
});

test("P presses during the query cycle from the detected mode", () => {
  const p = picker();
  p.root.nextPreview();
  p.root.nextPreview();
  p.reply("mirror");
  assert.equal(p.selected(), "internal");
  p.root.nextPreview();
  assert.equal(p.selected(), "external");
  p.root.nextPreview();
  assert.equal(p.selected(), "extend");
  assert.equal(p.reads.length, 1);
});

test("releasing both keys before the query finishes never applies extend", () => {
  const p = picker();
  p.root.nextPreview();
  p.root.observeKeys("switch-display-keys:false:false");
  assert.deepEqual(p.applied, []);
  p.reply("mirror");
  assert.deepEqual(p.applied, ["mirror"]);
});

test("another P press cancels a deferred release and preserves cycling", () => {
  const p = picker();
  p.root.nextPreview();
  p.root.commitPreview();
  p.root.nextPreview();
  p.reply("mirror");
  assert.equal(p.selected(), "internal");
  assert.deepEqual(p.applied, []);
});

test("cancelled query results cannot overwrite a reopened preview", () => {
  const p = picker();
  p.root.nextPreview();
  p.root.close();
  p.root.nextPreview();
  p.reply("mirror");
  assert.equal(p.root.readingLayout, true);
  assert.equal(p.root.selectedIndex, -1);
  assert.equal(p.reads.length, 2);
  p.reply("external");
  assert.equal(p.selected(), "external");
});

test("failed or malformed detection does not apply a guessed layout and can retry", () => {
  for (const [code, output] of [[1, '{"ok":false,"message":"disconnected"}'], [0, "{"], [0, '{"ok":true,"layout":"unknown"}']]) {
    const p = picker();
    p.root.nextPreview();
    p.root.commitPreview();
    p.reply("", code, output);
    assert.equal(p.root.statusError, true);
    assert.equal(p.root.armed, false);
    assert.deepEqual(p.applied, []);
    p.root.nextPreview();
    p.reply("external");
    assert.equal(p.selected(), "external");
    assert.equal(p.root.statusError, false);
  }
});
