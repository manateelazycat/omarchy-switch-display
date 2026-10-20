# SPDX-License-Identifier: GPL-3.0-only
"""Worker for run.py; refuses to run against an ordinary desktop session."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

if os.environ.get('MIRROR_REDRAW_SANDBOX') != '1' or list(Path('/dev/dri').glob('card*')) or Path('/run/user').exists():
    raise RuntimeError('This worker requires the private run.py sandbox')

root = Path('/tmp/lab')
runtime = root / 'runtime'
runtime.mkdir(mode=0o700, exist_ok=True)
(root / 'home').mkdir(exist_ok=True)
modules = list((root / 'weston/usr/lib').glob('**/*.so'))
os.environ['WESTON_MODULE_MAP'] = ';'.join(f'{p.name}={p}' for p in modules)
os.environ['LD_LIBRARY_PATH'] = '/tmp/lab/aq-build:/tmp/lab/weston/usr/lib:/tmp/lab/weston/usr/lib/weston'

def wait_for(predicate, message, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise RuntimeError(message)

def terminate(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

def run_case(binary, label):
    config = root / f'{label}.lua'
    config.write_text('''hl.monitor({output="", mode="1920x1200@60", position="auto-right", scale=1.5})
hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", position="auto-right", scale=1.5})
hl.config({debug={disable_logs=false, enable_stdout_logs=true}, animations={enabled=true}, misc={disable_hyprland_logo=true, disable_splash_rendering=true, background_color="rgb(224466)"}, render={direct_scanout=0}})
''')
    env = dict(os.environ, WAYLAND_DISPLAY='weston-test')
    before = set(runtime.glob('hypr/*/.socket.sock'))
    with (root / f'{label}.log').open('w') as log:
        hypr = subprocess.Popen([binary, '--config', str(config)], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            ipc_path = wait_for(lambda: next(iter(set(runtime.glob('hypr/*/.socket.sock')) - before), None), 'IPC not ready')
            def ipc(request):
                if hypr.poll() is not None:
                    raise RuntimeError(f'{label} compositor exited {hypr.returncode}')
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.settimeout(5)
                    sock.connect(str(ipc_path))
                    sock.sendall(request.encode())
                    parts = []
                    while True:
                        part = sock.recv(100000)
                        if not part:
                            break
                        parts.append(part)
                    return b''.join(parts).decode().strip()
            def ok(request):
                response = ipc('/' + request)
                if response != 'ok':
                    raise RuntimeError(f'{label}: {request}: {response}')
            def monitors():
                return json.loads(ipc('j/monitors all'))
            def target():
                return next((m for m in monitors() if m['name'] == 'TEST-MIRROR'), None)
            wait_for(lambda: len(monitors()) > 0, 'No initial monitor')
            ok('output create headless TEST-SOURCE')
            ok('output create headless TEST-MIRROR')
            wait_for(target, 'Headless output not ready')
            ok('plugin load /tmp/lab/mirror_probe.so')
            if label == 'patched' and (root / 'mirror-borders.so').exists():
                ok('plugin load /tmp/lab/mirror-borders.so')
            ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, disabled=false, mirror="TEST-SOURCE"})')
            wait_for(lambda: target()['mirrorOf'] != 'none', 'Initial mirror not established')
            for _ in range(6):
                ok('mirrortest tick TEST-SOURCE')
                time.sleep(0.04)
            time.sleep(0.3)
            assert (target()['width'], target()['height']) == (3840, 2160), target()
            assert ipc('/configerrors') == '', ipc('/configerrors')
            def phase(name, operation):
                seeded = ipc('/mirrortest seed TEST-MIRROR')
                if not seeded.isdigit() or int(seeded) < 2:
                    raise RuntimeError('Could not seed reused buffers: '+seeded)
                initial = json.loads(ipc('/mirrortest sample TEST-MIRROR'))
                assert initial[0] > 200 and initial[2] > 200, initial
                operation()
                wait_for(lambda: target()['mirrorOf'] != 'none', 'Mirror not established')
                for _ in range(16):
                    ok('mirrortest tick TEST-SOURCE')
                    time.sleep(0.04)
                samples = json.loads(ipc('/mirrortest samples TEST-MIRROR'))
                if len(samples) < 9 or any(v < 0 for sample in samples for v in sample):
                    raise RuntimeError(f'Missing valid framebuffer samples: {samples}')
                if any(sum(sample[6:]) < 20 for sample in samples[-9:]):
                    raise RuntimeError(f'Mirror content is blank: {samples}')
                result = {'phase':name, 'seeded_buffers':int(seeded), 'samples':samples, 'borders_black':all(v <= 1 for sample in samples for v in sample[:6]), 'geometry':{k:target()[k] for k in ['width','height','scale','mirrorOf']}}
                print(json.dumps({'label':label, **result}), flush=True)
                return result

            initial = json.loads(ipc('/mirrortest samples TEST-MIRROR'))
            assert initial and all(v >= 0 for row in initial for v in row), initial
            phases = [{'phase':'initial-mirror', 'samples':initial,
                       'borders_black':all(v <= 1 for row in initial for v in row[:6]),
                       'geometry':{k:target()[k] for k in ['width','height','scale','mirrorOf']}}]
            phases.append(phase('source-resize', lambda: ok('eval hl.monitor({output="TEST-SOURCE", mode="1920x1440@60"})')))
            phases.append(phase('target-rotation', lambda: ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, transform=2})')))
            phases.append(phase('source-rotation', lambda: ok('eval hl.monitor({output="TEST-SOURCE", transform=1})')))
            ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, mirror=""})')
            wait_for(lambda: target()['mirrorOf'] == 'none', 'Mirror not released')
            time.sleep(0.25)
            phases.append(phase('reenter-mirror', lambda: ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, disabled=false, mirror="TEST-SOURCE"})')))
            ok('eval hl.monitor({output="TEST-SOURCE", mode="1920x1200@60", scale=1.5, transform=0})')
            ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, transform=0, disabled=false, mirror="TEST-SOURCE"})')
            for _ in range(6):
                ok('mirrortest tick TEST-SOURCE')
                time.sleep(0.04)
            def disable_enable():
                ok('eval hl.monitor({output="TEST-MIRROR", disabled=true})')
                wait_for(lambda: target() and target()['disabled'], 'Target not disabled')
                ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, disabled=false, mirror="TEST-SOURCE"})')
                ok('mirrortest tick TEST-SOURCE')
                wait_for(lambda: target() and not target()['disabled'], 'Target not enabled')
            phases.append(phase('disabled-to-mirror', disable_enable))
            phases.append(phase('explicit-soft-repaint', lambda: ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, disabled=false, mirror="TEST-SOURCE", sdrbrightness=1.0001})')))
            reconnects = []
            if label == 'patched':
                for attempt in range(3):
                    ok('mirrortest clear TEST-MIRROR')
                    ok('mirrortest remove TEST-MIRROR')
                    wait_for(lambda: target() is None, 'Target not removed')
                    ok('output create headless TEST-MIRROR')
                    wait_for(lambda: target() and target()['mirrorOf'] != 'none', 'Reconnected mirror not restored')
                    ok('eval hl.monitor({output="TEST-MIRROR", mode="3840x2160@60", scale=1.5, transform=0, disabled=false, mirror="TEST-SOURCE"})')
                    for _ in range(16):
                        ok('mirrortest tick TEST-SOURCE')
                        time.sleep(0.04)
                    pixels = json.loads(ipc('/mirrortest sample TEST-MIRROR'))
                    assert all(0 <= v <= 1 for v in pixels), pixels
                    frames = json.loads(ipc('/mirrortest samples TEST-MIRROR'))
                    assert len(frames) >= 9 and all(v <= 1 for row in frames for v in row[:6]), frames
                    assert all(sum(row[6:]) >= 20 for row in frames[-9:]), frames
                    assert (target()['width'], target()['height']) == (3840, 2160), target()
                    reconnects.append({'id':target()['id'], 'pixels':pixels, 'mirrorOf':target()['mirrorOf'], 'samples':frames})
                reconnect_pixels = json.loads(ipc('/mirrortest sample TEST-MIRROR'))
                assert all(0 <= v <= 1 for v in reconnect_pixels[:6]), reconnect_pixels
            phases.append(phase('top-bottom-bars', lambda: ok('eval hl.monitor({output="TEST-SOURCE", mode="1920x800@60"})')))
            ok('mirrortest clear TEST-MIRROR')
            ok('mirrortest missing-source TEST-MIRROR')
            time.sleep(0.08)
            pending = json.loads(ipc('/mirrortest samples TEST-MIRROR'))
            assert pending and all(v <= 1 for row in pending for v in row[:6]), pending
            for _ in range(9):
                ok('mirrortest tick TEST-SOURCE')
                time.sleep(0.04)
            assert ipc('/configerrors') == '', ipc('/configerrors')
            loader_preserved_layout = None
            if label == 'patched' and (root / 'mirror-borders.so').exists():
                ok('plugin unload /tmp/lab/mirror-borders.so')
                wait_for(lambda: target()['mirrorOf'] == 'none', 'Plugin unload config reload not complete')
                # Use the headless backend's advertised 1080p target mode here;
                # physical 4K outputs advertise 4K, while this test backend does not.
                ok('eval hl.monitor({output="TEST-SOURCE", mode="1600x1200@60", scale=1, transform=0})')
                ok('eval hl.monitor({output="TEST-MIRROR", mode="1920x1080@60", scale=1.5, transform=0, disabled=false, mirror="TEST-SOURCE"})')
                def runtime_layout_ready():
                    source = next(m for m in monitors() if m['name'] == 'TEST-SOURCE')
                    return (source['width'] == 1600 and source['height'] == 1200 and source['scale'] == 1
                            and target()['width'] == 1920 and target()['mirrorOf'] != 'none')
                wait_for(runtime_layout_ready, 'Runtime mirror not established')
                def layout():
                    keys = ['name','width','height','scale','transform','x','y','mirrorOf','disabled']
                    # Mirrors have no independent placement. Hyprland can leave
                    # their reported x/y at the source's temporary staged position.
                    return {m['name']:{k:m.get(k) for k in keys
                                      if k not in ('x','y') or m['mirrorOf'] == 'none'}
                            for m in monitors()}
                saved_layout = layout()
                loader_env = dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE=ipc_path.parent.name)
                loaded = subprocess.run([sys.executable, str(root / 'load_hotfix.py')], env=loader_env,
                                        text=True, capture_output=True, timeout=15)
                assert loaded.returncode == 0, (loaded.stdout, loaded.stderr)
                loader_preserved_layout = saved_layout == layout()
                assert loader_preserved_layout, (saved_layout, layout())
                loaded = subprocess.run([sys.executable, str(root / 'load_hotfix.py')], env=loader_env,
                                        text=True, capture_output=True, timeout=10)
                assert loaded.returncode == 0 and 'already loaded' in loaded.stdout, (loaded.stdout, loaded.stderr)
            result = {'label':label, 'phases':phases, 'reconnects':reconnects, 'borders_black':all(p['borders_black'] for p in phases), 'monitors':monitors()}
            result['loader_preserved_layout'] = loader_preserved_layout
            (root / f'{label}-result.json').write_text(json.dumps(result, indent=2)+'\n')
            return result
        finally:
            terminate(hypr)

weston_log = (root / 'weston-regression.log').open('w')
weston = subprocess.Popen(['/tmp/lab/weston/usr/bin/weston', '--backend=headless', '--renderer=gl', '--shell=kiosk-shell.so', '--socket=weston-test', '--width=1920', '--height=1200', '--idle-time=0', '--no-config', '--fake-seat'], stdout=weston_log, stderr=subprocess.STDOUT)
try:
    wait_for(lambda: (runtime / 'weston-test').exists(), 'Weston not ready')
    baseline = run_case('/tmp/lab/baseline-Hyprland', 'baseline')
    patched = run_case('/tmp/lab/build/Hyprland', 'patched')
    assert not baseline['borders_black'], 'Baseline failed to reproduce the defect'
    assert patched['borders_black'], 'Patched output retained old border pixels'
    print('PASS: every sampled mirror border stays black across startup, disable/enable, three reconnects, rotation, resizing and pending source frames.', flush=True)
finally:
    terminate(weston)
