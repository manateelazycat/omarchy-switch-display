// SPDX-License-Identifier: GPL-3.0-only
// Runtime counterpart of the Hyprland 0.56.2 mirror reconnect patch.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <algorithm>
#include <stdexcept>
#include <string_view>

static CHyprSignalListener renderListener;
static CHyprSignalListener layoutListener;
static CHyprSignalListener fallbackListener;

static void invalidateMirror(PHLMONITOR monitor) {
    if (!monitor || !monitor->m_output || !monitor->m_enabled || !monitor->isMirror())
        return;

    monitor->m_damage.damageEntire();
    monitor->m_forceFullFrames = std::max(monitor->m_forceFullFrames, 3);
    monitor->scheduleFrame(Aquamarine::IOutput::AQ_SCHEDULE_DAMAGE);
}

static void prepareMirror(PHLMONITOR monitor) {
    if (!monitor || !monitor->m_output || !monitor->m_enabled || !monitor->isMirror())
        return;

    // The final-copy zoom can paint source pixels into the pillarboxes. Its
    // animation callback calls damageMonitor(), which ignores mirror outputs.
    // End this target-only transition before its first frame, including the
    // five presentation callbacks that otherwise reset the zoom to 2x.
    if (monitor->m_zoomAnimProgress->value() != 1.F || monitor->m_zoomAnimFrameCounter < 5) {
        monitor->m_zoomAnimFrameCounter = 5;
        monitor->m_zoomAnimProgress->setValueAndWarp(1.F);
        invalidateMirror(monitor);
    }
}

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE) {
    if (std::string_view{__hyprland_api_get_hash()} != __hyprland_api_get_client_hash() ||
        std::string_view{GIT_COMMIT_HASH} != "efb50993780079460b0cbed1363e2166a2de1d9f")
        throw std::runtime_error("mirror-borders requires matching Hyprland 0.56.2 headers and libraries");

    renderListener = Event::bus()->m_events.render.pre.listen(prepareMirror);
    layoutListener = Event::bus()->m_events.monitor.layoutChanged.listen([] {
        for (const auto& monitor : State::monitorState()->allMonitors())
            invalidateMirror(monitor);
    });
    fallbackListener = Event::bus()->m_events.render.stage.listen([](eRenderStage stage) {
        if (stage != RENDER_POST_MIRROR)
            return;
        const auto monitor = g_pHyprRenderer->m_renderData.pMonitor.lock();
        if (!monitor || !monitor->isMirror())
            return;
        const auto source = monitor->m_mirrorOf.lock();
        // renderMirrored() returns before its clear when the source framebuffer
        // is absent. Clear the target rather than present its previous contents.
        if (!source || !source->resources()->hasMirrorFB())
            g_pHyprRenderer->m_renderPass.add(makeUnique<CClearPassElement>(CClearPassElement::SClearData{CHyprColor(0, 0, 0, 1)}));
    });

    for (const auto& monitor : State::monitorState()->allMonitors()) {
        prepareMirror(monitor);
        invalidateMirror(monitor);
    }
    return {"mirror-borders", "Keep mirrored outputs black outside the source image on reconnect", "Andy Stewart", "1.0.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    renderListener.reset();
    layoutListener.reset();
    fallbackListener.reset();
}
