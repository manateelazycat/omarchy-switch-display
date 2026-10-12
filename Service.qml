// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Andy Stewart

import QtQuick
import qs.Commons
import qs.Ui
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
      color: Color.menu.scrim

      BorderSurface {
        id: dialog
        width: Math.min(Style.space(920), parent.width - Style.spacing.panelPadding * 2)
        height: content.implicitHeight + Style.spacing.panelPadding * 2
        anchors.centerIn: parent
        radius: Style.cornerRadius
        color: Color.menu.background
        borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(2)))

        Column {
          id: content
          anchors.fill: parent
          anchors.margins: Style.spacing.panelPadding
          spacing: Style.spacing.panelGap

          Row {
            width: parent.width
            Column {
              spacing: Style.spacing.labelGap
              Text { text: "切换显示模式"; color: Color.menu.text; font.family: Style.font.menuFamily; font.pixelSize: Style.font.heading; font.weight: Font.DemiBold }
              Text { text: "按住 Super，反复按 P 预览；松开两键后应用"; color: Util.alpha(Color.menu.text, 0.7); font.family: Style.font.menuFamily; font.pixelSize: Style.font.subtitle }
            }
          }

          Row {
            width: parent.width
            spacing: Style.spacing.controlGap
            Repeater {
              model: root.layouts
              delegate: BorderSurface {
                required property var modelData
                property var card: modelData
                required property int index
                readonly property bool selected: root.selectedIndex === index
                width: (parent.width - parent.spacing * 3) / 4
                height: Math.max(Style.space(146), cardContent.implicitHeight + Style.spacing.rowPaddingX * 2)
                radius: Style.cornerRadius
                color: selected ? Color.menu.selectedBackground : Style.normalFill
                borderSpec: selected
                  ? Border.surfaceSpec("menu", "selected-border", Color.menu.selectedBorder, Style.space(1))
                  : Border.controlSpec("normal", Color.menu.text, Color.accent, Color.urgent)

                Column {
                  id: cardContent
                  anchors.fill: parent
                  anchors.margins: Style.spacing.rowPaddingX
                  spacing: Style.spacing.controlGap
                  Item {
                    width: parent.width
                    height: Style.space(62)
                    DisplayLayoutIcon {
                      anchors.centerIn: parent
                      layout: card.icon
                      color: selected ? Color.menu.selectedText : Color.menu.text
                      highlighted: selected
                      width: Style.space(96)
                      height: Style.space(62)
                    }
                  }
                  Text { text: card.title; color: selected ? Color.menu.selectedText : Color.menu.text; font.family: Style.font.menuFamily; font.pixelSize: Style.font.title; font.weight: Font.DemiBold }
                  Text { text: card.hint; color: Util.alpha(Color.menu.text, 0.7); font.family: Style.font.menuFamily; font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight; width: parent.width; wrapMode: Text.Wrap }
                }
              }
            }
          }

          Text {
            visible: root.statusText.length > 0
            text: root.statusText
            color: root.statusError ? Color.urgent : Color.menu.text
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.Wrap
            width: parent.width
          }
          Text { text: root.layouts[root.selectedIndex].title + "  ·  松开 Super 和 P 后应用"; color: Color.menu.selectedText; font.family: Style.font.menuFamily; font.pixelSize: Style.font.body; anchors.horizontalCenter: parent.horizontalCenter }
        }
      }
    }

  }
}
