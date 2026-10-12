// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Andy Stewart

import QtQuick
import QtQuick.VectorImage

Item {
  id: root

  required property string layout
  property bool highlighted: false
  implicitWidth: 96
  implicitHeight: 62

  VectorImage {
    anchors.fill: parent
    source: Qt.resolvedUrl("icons/" + root.layout + ".svg")
    fillMode: VectorImage.PreserveAspectFit
    preferredRendererType: VectorImage.CurveRenderer
    opacity: root.highlighted ? 1 : 0.72
  }
}
