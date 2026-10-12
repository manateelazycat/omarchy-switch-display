// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Andy Stewart

import QtQuick
import QtQuick.Shapes

Item {
  id: root

  property bool internal: false
  property int contentVariant: 0
  property bool highlighted: false
  readonly property color outlineColor: highlighted ? "#ecf3ff" : "#c0cbdc"
  implicitWidth: 64
  implicitHeight: 52

  // Draw in one coordinate system so paired and single devices share a weight.
  Item {
    width: 64
    height: 52
    anchors.centerIn: parent
    scale: Math.min(root.width / width, root.height / height)

    Rectangle {
      x: root.internal ? 10 : 19
      y: 46
      width: root.internal ? 44 : 26
      height: 3
      radius: 1.5
      color: "#101722"
      opacity: 0.3
    }

    Shape {
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: root.outlineColor
        strokeWidth: 1.5
        joinStyle: ShapePath.RoundJoin
        fillGradient: LinearGradient {
          x1: 0; y1: 4; x2: 0; y2: 38
          GradientStop { position: 0; color: "#34465f" }
          GradientStop { position: 1; color: "#202d41" }
        }
        PathSvg {
          path: root.internal
            ? "M12 7 H52 Q55 7 55 10 V37 H9 V10 Q9 7 12 7 Z"
            : "M8 3 H56 Q59 3 59 6 V33 Q59 36 56 36 H8 Q5 36 5 33 V6 Q5 3 8 3 Z"
        }
      }

      ShapePath {
        strokeColor: "transparent"
        fillGradient: LinearGradient {
          x1: 9; y1: 9; x2: 52; y2: 35
          GradientStop { position: 0; color: root.highlighted ? "#a1cfff" : "#7c9dc3" }
          GradientStop { position: 0.5; color: root.highlighted ? "#528be2" : "#4a6e9e" }
          GradientStop { position: 1; color: root.highlighted ? "#315da8" : "#334d74" }
        }
        PathSvg {
          path: root.internal
            ? "M13 10 H51 Q52 10 52 11 V33.5 H12 V11 Q12 10 13 10 Z"
            : "M9 6 H55 Q56 6 56 7 V30.5 H8 V7 Q8 6 9 6 Z"
        }
      }

      // Two halves of a continuous desktop; mirrors use the same half.
      ShapePath {
        strokeColor: "transparent"
        fillColor: root.highlighted ? "#b0d6ff" : "#90acce"
        PathSvg {
          path: root.internal
            ? (root.contentVariant === 0
              ? "M12 28 C21 16 33 17 52 12 V23 C38 23 25 27 12 33.5 Z"
              : "M12 12 C28 19 39 18 52 28 V33.5 H12 Z")
            : (root.contentVariant === 0
              ? "M8 25 C19 13 35 14 56 8 V20 C39 20 23 24 8 30.5 Z"
              : "M8 8 C28 16 43 14 56 25 V30.5 H8 Z")
        }
      }

      ShapePath {
        strokeColor: "transparent"
        fillColor: root.highlighted ? "#4e8ee1" : "#5378a3"
        PathSvg {
          path: root.internal
            ? (root.contentVariant === 0
              ? "M12 31 C24 27 37 23 52 23 V33.5 H12 Z"
              : "M12 24 C28 24 40 28 52 33.5 H12 Z")
            : (root.contentVariant === 0
              ? "M8 28 C24 24 39 20 56 20 V30.5 H8 Z"
              : "M8 21 C28 21 43 26 56 30.5 H8 Z")
        }
      }
    }

    Shape {
      visible: root.internal
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: root.outlineColor
        strokeWidth: 1.4
        joinStyle: ShapePath.RoundJoin
        fillGradient: LinearGradient {
          x1: 0; y1: 37; x2: 0; y2: 44
          GradientStop { position: 0; color: "#c4d0e0" }
          GradientStop { position: 1; color: "#8194ae" }
        }
        PathSvg { path: "M9 37 H55 L61 41 Q61 44 57 44 H7 Q3 44 3 41 Z" }
      }

      ShapePath {
        strokeColor: "#53657e"
        strokeWidth: 1
        capStyle: ShapePath.RoundCap
        fillColor: "#53657e"
        PathSvg { path: "M26 37.8 H38 L36.5 39.6 H27.5 Z" }
      }

      ShapePath {
        strokeColor: "#e3ebf7"
        strokeWidth: 0.8
        capStyle: ShapePath.RoundCap
        fillColor: "transparent"
        PathSvg { path: "M6 41 H58" }
      }
    }

    Shape {
      visible: !root.internal
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: root.outlineColor
        strokeWidth: 1.4
        joinStyle: ShapePath.RoundJoin
        fillGradient: LinearGradient {
          x1: 0; y1: 36; x2: 0; y2: 46
          GradientStop { position: 0; color: "#b1bfd3" }
          GradientStop { position: 1; color: "#7d91ac" }
        }
        PathSvg { path: "M29 36 H35 L36 43 L43 45 V46 H21 V45 L28 43 Z" }
      }

      ShapePath {
        strokeColor: "#7186a4"
        strokeWidth: 0.8
        capStyle: ShapePath.RoundCap
        fillColor: "transparent"
        PathSvg { path: "M8 32 H56" }
      }
    }

    Rectangle {
      x: 30.5
      y: root.internal ? 8 : 33
      width: 3
      height: 1
      radius: 0.5
      color: root.outlineColor
      opacity: 0.65
    }
  }
}
