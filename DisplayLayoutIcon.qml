// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Andy Stewart

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import QtQuick.VectorImage

Item {
  id: root

  required property string layout
  property bool highlighted: false
  required property color color
  implicitWidth: 96
  implicitHeight: 62

  VectorImage {
    anchors.fill: parent
    source: Qt.resolvedUrl("icons/" + root.layout + ".svg")
    fillMode: VectorImage.PreserveAspectFit
    preferredRendererType: VectorImage.CurveRenderer
    opacity: root.highlighted ? 1 : 0.72
    layer.enabled: true
    layer.effect: MultiEffect {
      colorization: 1
      colorizationColor: root.color
    }
  }
}
