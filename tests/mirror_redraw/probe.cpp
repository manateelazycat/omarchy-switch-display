// SPDX-License-Identifier: GPL-3.0-only
// Test fixture only. Load exclusively in the sandboxed compositor.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderbuffer.hpp>
#include <GLES3/gl3.h>
#include <aquamarine/backend/Backend.hpp>
#include <array>
#include <map>
#include <sstream>
#include <algorithm>
#include <cmath>

using namespace Render;
using namespace Render::GL;

static CHyprSignalListener listener;
static CHyprSignalListener preListener;
static SP<SHyprCtlCommand> command;
static std::map<std::string, std::vector<std::array<int, 9>>> samples;

static PHLMONITOR findMonitor(const std::string& name) {
    for (const auto& monitor : State::monitorState()->allMonitors()) {
        if (monitor->m_name == name)
            return monitor;
    }
    return nullptr;
}

static std::array<int, 9> readBorders(PHLMONITOR monitor) {
    auto buffer = monitor->m_output->state->state().buffer;
    if (!buffer)
        return {-1, -1, -1, -1, -1, -1, -1, -1, -1};
    g_pHyprOpenGL->makeEGLCurrent();
    auto renderbuffer = g_pHyprRenderer->getOrCreateRenderbuffer(buffer, monitor->m_output->state->state().drmFormat);
    GLint previous;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &previous);
    renderbuffer->bind();
    std::array<unsigned char, 4> left{}, right{}, center{};
    const auto source = monitor->m_mirrorOf.lock();
    const auto size = source ? source->m_transformedSize : Vector2D{1920, 1200};
    const auto fit = std::min(monitor->m_transformedSize.x / size.x, monitor->m_transformedSize.y / size.y);
    const int width = int(monitor->m_pixelSize.x), height = int(monitor->m_pixelSize.y);
    const int horizontal = std::max(0, int(std::floor((monitor->m_transformedSize.x - size.x * fit) / 2)));
    const int vertical = std::max(0, int(std::floor((monitor->m_transformedSize.y - size.y * fit) / 2)));
    auto readRegion = [&](int x, int y, int w, int h, auto& maximum) {
        if (w <= 0 || h <= 0)
            return;
        std::vector<unsigned char> pixels(size_t(w) * h * 4);
        glReadPixels(x, y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        for (size_t i = 0; i < pixels.size(); i += 4)
            for (int c = 0; c < 3; ++c)
                maximum[c] = std::max(maximum[c], pixels[i + c]);
    };
    // Read all border pixels, including glyphs away from the midpoint. Omit
    // only the final pixel at the scaled content seam to avoid filtering noise.
    if (horizontal > 1) {
        readRegion(0, 0, horizontal - 1, height, left);
        readRegion(width - horizontal + 1, 0, horizontal - 1, height, right);
    } else if (vertical > 1) {
        readRegion(0, 0, width, vertical - 1, left);
        readRegion(0, height - vertical + 1, width, vertical - 1, right);
    }
    glReadPixels(int(monitor->m_pixelSize.x / 2), int(monitor->m_pixelSize.y / 2), 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center.data());
    const auto error = glGetError();
    glBindFramebuffer(GL_FRAMEBUFFER, previous);
    if (error != GL_NO_ERROR)
        return {-2, -2, -2, -2, -2, -2, -2, -2, -2};
    return {left[0], left[1], left[2], right[0], right[1], right[2], center[0], center[1], center[2]};
}

static std::string request(eHyprCtlOutputFormat, std::string input) {
    std::istringstream stream(input);
    std::string prefix, action, name;
    stream >> prefix >> action >> name;
    auto monitor = findMonitor(name);
    if (!monitor || !monitor->m_output)
        return "missing monitor";
    if (action == "clear") {
        samples[name].clear();
        return "ok";
    }
    if (action == "missing-source") {
        const auto source = monitor->m_mirrorOf.lock();
        if (!source)
            return "missing source";
        source->resources()->releaseMirrorFB();
        monitor->m_damage.damageEntire();
        monitor->scheduleFrame();
        return "ok";
    }
    if (action == "remove") {
        if (monitor->m_output->getBackend()->type() != Aquamarine::AQ_BACKEND_HEADLESS)
            return "fixture refuses non-headless output";
        return monitor->m_output->destroy() ? "ok" : "destroy failed";
    }
    if (action == "seed") {
        if (monitor->m_output->getBackend()->type() != Aquamarine::AQ_BACKEND_HEADLESS)
            return "fixture refuses non-headless output";
        g_pHyprOpenGL->makeEGLCurrent();
        GLint previous;
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &previous);
        const auto count = monitor->m_output->swapchain->currentOptions().length;
        for (size_t i = 0; i < count; ++i) {
            int age;
            auto buffer = monitor->m_output->swapchain->next(&age);
            if (!buffer)
                return "missing buffer";
            auto rb = g_pHyprRenderer->getOrCreateRenderbuffer(buffer, monitor->m_output->state->state().drmFormat);
            rb->bind();
            glDisable(GL_SCISSOR_TEST);
            std::array<float, 4> color = {1, float(i % 2), 1, 1};
            glClearBufferfv(GL_COLOR, 0, color.data());
        }
        glBindFramebuffer(GL_FRAMEBUFFER, previous);
        glFinish();
        for (int i = 0; i < 5; ++i)
            monitor->m_damage.rotate();
        monitor->m_forceFullFrames = 0;
        samples[name].clear();
        return std::to_string(count);
    }
    if (action == "tick") {
        monitor->m_damage.damageEntire();
        monitor->scheduleFrame();
        return "ok";
    }
    if (action == "sample") {
        const auto p = readBorders(monitor);
        return std::format("[{},{},{},{},{},{}]", p[0], p[1], p[2], p[3], p[4], p[5]);
    }
    if (action == "samples") {
        std::string result = "[";
        for (const auto& sample : samples[name]) {
            if (result.size() > 1)
                result += ',';
            result += std::format("[{},{},{},{},{},{},{},{},{}]", sample[0], sample[1], sample[2], sample[3], sample[4], sample[5], sample[6], sample[7], sample[8]);
        }
        return result + "]";
    }
    return "unknown action";
}

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }
APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    // This guard prevents loading this fixture into an ordinary desktop.
    if (std::string{getenv("XDG_RUNTIME_DIR") ?: ""} != "/tmp/lab/runtime" || std::string{getenv("MIRROR_REDRAW_SANDBOX") ?: ""} != "1")
        throw std::runtime_error("mirror test fixture requires isolated runtime");
    command = HyprlandAPI::registerHyprCtlCommand(handle, {"mirrortest", false, request});
    preListener = Event::bus()->m_events.render.pre.listen([](PHLMONITOR m) {
        if (m->m_name == "TEST-MIRROR") {
            auto box = m->m_damage.getBufferDamage(3).getExtents();
            fprintf(stderr, "TEST-DAMAGE: full=%d mirror=%d box=%.0f,%.0f,%.0f,%.0f\n", m->m_forceFullFrames, m->isMirror(), box.x, box.y, box.w, box.h);
        }
    });
    listener = Event::bus()->m_events.render.stage.listen([](eRenderStage stage) {
        if (stage != RENDER_POST)
            return;
        // OpenGL::end resets renderData.pMonitor; inspect the retained output buffers on request instead.
        for (const auto& m : State::monitorState()->allMonitors()) {
            if (m->isMirror() && m->m_renderingActive)
                samples[m->m_name].push_back(readBorders(m));
        }
    });
    return {"mirror-test-fixture", "Offscreen mirror pixel regression", "Andy Stewart", "1"};
}
APICALL EXPORT void PLUGIN_EXIT() { listener.reset(); preListener.reset(); command.reset(); }
