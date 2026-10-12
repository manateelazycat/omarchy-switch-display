// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Andy Stewart

import QtQuick
import Quickshell
import Quickshell.Hyprland._GlobalShortcuts 0.0
import Quickshell.Io
import Quickshell.Wayland

Item {
  id: root

  property bool opened: false
  property bool busy: false
  property bool committing: false
  property bool armed: false
  property int selectedIndex: 0
  property string statusText: ""
  property bool statusError: false
  readonly property var layouts: [
    { id: "extend", title: "扩展屏幕", hint: "并排使用每个显示器", icon: "extend" },
    { id: "mirror", title: "镜像屏幕", hint: "所有屏幕显示相同内容", icon: "mirror" },
    { id: "internal", title: "仅显示内屏", hint: "关闭外屏，使用内屏最大分辨率", icon: "internal" },
    { id: "external", title: "仅显示外屏", hint: "关闭内屏，使用外屏最大分辨率", icon: "external" }
  ]
  readonly property string helperPath: {
    var url = String(Qt.resolvedUrl("apply_layout.py"))
    try { return decodeURIComponent(url.replace(/^file:\/\//, "")) }
    catch (error) { return url.replace(/^file:\/\//, "") }
  }

  function nextPreview() {
    if (root.busy) return
    root.armed = true
    if (!root.opened) {
      root.opened = true
      root.selectedIndex = 0
      root.committing = false
    } else {
      root.selectedIndex = (root.selectedIndex + 1) % root.layouts.length
      root.committing = false
    }
    root.statusText = ""
    root.statusError = false
  }

  function commitPreview() {
    if (!root.opened || root.busy || root.committing) return
    root.armed = false
    root.committing = true
    root.apply(root.layouts[root.selectedIndex].id)
  }

  function observeKeys(output) {
    if (!root.opened || !root.armed || root.busy || root.committing) return
    var state = String(output || "").match(/switch-display-keys:(true|false):(true|false)/)
    if (state && state[1] === "false" && state[2] === "false")
      root.commitPreview()
  }

  function close() {
    if (!root.busy) root.opened = false
  }

  function apply(layout) {
    if (root.busy) return
    root.busy = true
    root.statusText = "按键已松开，正在应用布局…"
    root.statusError = false
    // Release focus and unmap while the current output still exists. The
    // helper waits until Hyprland confirms this layer surface is gone.
    root.armed = false
    root.opened = false
    applyProcess.command = ["/usr/bin/python3", root.helperPath, layout]
    applyProcess.running = true
  }

  IpcHandler {
    target: "andy.switch-display"
    function status(): string {
      return JSON.stringify({ opened: root.opened, armed: root.armed, busy: root.busy,
        committing: root.committing, layout: root.layouts[root.selectedIndex].id,
        message: root.statusText, error: root.statusError,
        mirrorAllowed: true, mirrorReason: "" })
    }
    function toggle(): void { root.nextPreview() }
    function show(): void { root.nextPreview() }
    function hide(): void { root.close() }
  }

  GlobalShortcut {
    name: "andySwitchDisplayNext"
    description: "Switch Display: preview next layout"
    onPressed: root.nextPreview()
  }

  Timer {
    interval: 60
    repeat: true
    running: root.opened && root.armed && !root.busy
    onTriggered: if (!keyStateProcess.running) keyStateProcess.running = true
  }

  Process {
    id: keyStateProcess
    command: ["hyprctl", "eval", 'error("switch-display-keys:" .. tostring(hl.is_key_down("Super_L") or hl.is_key_down("Super_R")) .. ":" .. tostring(hl.is_key_down("P")))']
    stdout: StdioCollector { onStreamFinished: root.observeKeys(text) }
  }

  Process {
    id: applyProcess
    stdout: StdioCollector { id: applyOutput; waitForEnd: true }
    stderr: StdioCollector { id: applyError; waitForEnd: true }
    onExited: function(exitCode) {
      root.busy = false
      try {
        var result = JSON.parse(String(applyOutput.text || "{}"))
        root.statusError = exitCode !== 0 || !result.ok
        root.statusText = String(result.message || "切换显示布局失败")
        root.opened = root.statusError
      } catch (error) {
        root.statusError = true
        root.opened = true
        root.statusText = String(applyError.text || "切换显示布局失败").trim()
      }
      root.committing = false
    }
  }

  PanelWindow {
    screen: Quickshell.screens.length ? Quickshell.screens[0] : null
    visible: root.opened
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "andy-switch-display"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened && !root.busy ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    anchors { top: true; bottom: true; left: true; right: true }

    Rectangle {
      anchors.fill: parent
      color: "#99070b12"

      Rectangle {
        id: dialog
        width: 920
        height: content.implicitHeight + 42
        anchors.centerIn: parent
        radius: 20
        color: "#171b24"
        border.color: "#343b49"
        border.width: 1

        Column {
          id: content
          anchors.fill: parent
          anchors.margins: 22
          spacing: 16

          Row {
            width: parent.width
            Column {
              spacing: 4
              Text { text: "切换显示模式"; color: "#f5f7fb"; font.pixelSize: 21; font.weight: Font.DemiBold }
              Text { text: "按住 Super，反复按 P 预览；松开两键后应用"; color: "#a6afbd"; font.pixelSize: 13 }
            }
          }

          Row {
            width: parent.width
            spacing: 8
            Repeater {
              model: root.layouts
              delegate: Rectangle {
                required property var modelData
                property var card: modelData
                required property int index
                width: (parent.width - 24) / 4
                height: 146
                radius: 14
                color: root.selectedIndex === index ? "#293b59" : "#202633"
                border.color: root.selectedIndex === index ? "#8db3ff" : "#353e4e"
                border.width: 1

                Column {
                  anchors.fill: parent
                  anchors.margins: 12
                  spacing: 8
                  Item {
                    width: parent.width
                    height: 62
                    DisplayLayoutIcon {
                      anchors.centerIn: parent
                      layout: card.icon
                      highlighted: root.selectedIndex === index
                    }
                  }
                  Text { text: card.title; color: "#f3f5fa"; font.pixelSize: 14; font.weight: Font.DemiBold }
                  Text { text: card.hint; color: "#a6afbd"; font.pixelSize: 11; elide: Text.ElideRight; width: parent.width; wrapMode: Text.Wrap }
                }
              }
            }
          }

          Text {
            visible: root.statusText.length > 0
            text: root.statusText
            color: root.statusError ? "#ff8c8c" : "#a6afbd"
            font.pixelSize: 12
            wrapMode: Text.Wrap
            width: parent.width
          }
          Text { text: root.layouts[root.selectedIndex].title + "  ·  松开 Super 和 P 后应用"; color: "#8db3ff"; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter }
        }
      }
    }

  }
}
