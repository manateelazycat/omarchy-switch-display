// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Andy Stewart

import QtQuick
import QtQuick.Shapes

Item {
  id: root

  required property string layout
  property bool highlighted: false
  readonly property bool paired: layout === "extend" || layout === "mirror"
  readonly property color symbolColor: highlighted ? "#a8cdff" : "#8399b6"
  implicitWidth: paired ? 144 : 76
  implicitHeight: 62

  DisplayIcon {
    internal: root.paired || root.layout === "internal"
    contentVariant: 0
    highlighted: root.highlighted
    width: root.paired ? 60 : 76
    height: root.paired ? 49 : 62
    anchors.verticalCenter: parent.verticalCenter
    x: root.paired ? 0 : (parent.width - width) / 2
  }

  DisplayIcon {
    visible: root.paired
    internal: false
    contentVariant: root.layout === "extend" ? 1 : 0
    highlighted: root.highlighted
    width: 60
    height: 49
    anchors.verticalCenter: parent.verticalCenter
    x: 84
  }

  Shape {
    visible: root.paired
    x: 62
    y: (parent.height - height) / 2 - 3
    width: 20
    height: 14
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
      strokeColor: root.symbolColor
      strokeWidth: 1.5
      capStyle: ShapePath.RoundCap
      joinStyle: ShapePath.RoundJoin
      fillColor: "transparent"
      PathSvg {
        path: root.layout === "extend"
          ? "M2 7 H18 M5.5 3.5 L2 7 L5.5 10.5 M14.5 3.5 L18 7 L14.5 10.5"
          : "M4 4.5 H16 M4 9.5 H16"
      }
    }
  }
}
