"""Live policy verification, manipulating only a temporary owned preview window."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from controller_wayland import ROOT, module


async def until(predicate, label):
    async with asyncio.timeout(12):
        while not predicate():
            await asyncio.sleep(0.1)
    print('PASS:', label)


def windows():
    return json.loads(subprocess.check_output(['niri', 'msg', '-j', 'windows']))


def action(name, window):
    subprocess.run(['niri', 'msg', 'action', name, '--id', str(window)],
                   check=True, stdout=subprocess.DEVNULL)


async def main():
    original = next((w['id'] for w in windows() if w['is_focused']), None)
    output = next(iter(json.loads(subprocess.check_output(['niri', 'msg', '-j', 'outputs']))))
    os.environ['QT_QPA_PLATFORM'] = 'wayland'
    local_plugins = ROOT / '.deps/layer-shell-qt/usr/lib/qt6/plugins'
    if local_plugins.exists():
        os.environ['QT_PLUGIN_PATH'] = str(local_plugins)
    with tempfile.TemporaryDirectory(prefix='vwallpaper-policy-live-') as directory:
        root = Path(directory)
        clip = root / 'clip.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=640x360:rate=30', '-t', '2', '-c:v',
                        'libx264', '-pix_fmt', 'yuv420p', str(clip)], check=True)
        control = module.Controller(root / 'state', str(ROOT / 'build/vwallpaper-renderer'))
        tasks = [asyncio.create_task(coro) for coro in
                 (control.watch_niri(), control.watch_environment(), control.policy_loop())]
        preview = None
        try:
            await until(lambda: control.niri.connected and control.environment.get('foreign_available'),
                        'Niri and foreign-toplevel subscription')
            await control.command({'action': 'sync', 'outputs': [output],
                                   'settings': {'optimize': True, 'fps': 15, 'height': 720, 'ac_only': False}})
            await control.command({'action': 'set', 'output': output, 'path': str(clip)})
            assert output in control.players, control.errors
            player = control.players[output]
            assert player.playback_path != str(clip)
            assert control.profiles[output]['path'] == str(clip)
            print('PASS: optimized copy plays with original assignment preserved')
            preview = await asyncio.create_subprocess_exec(control.renderer, '--preview', '--file', str(clip),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await until(lambda: any(w.get('pid') == preview.pid for w in control.niri.windows.values()),
                        'owned preview registered')
            window = next(w['id'] for w in control.niri.windows.values() if w.get('pid') == preview.pid)
            action('fullscreen-window', window)
            await until(lambda: 'fullscreen' in player.reasons, 'visible fullscreen pauses wallpaper')
            await control.command({'action': 'pause', 'output': output, 'paused': True})
            action('fullscreen-window', window)
            await until(lambda: player.reasons == {'manual'}, 'leaving fullscreen preserves manual pause')
            await control.command({'action': 'pause', 'output': output, 'paused': False})
            await until(lambda: not player.reasons, 'manual resume clears last reason')
            action('toggle-windowed-fullscreen', window)
            await asyncio.sleep(0.8)
            assert 'fullscreen' not in player.reasons
            print('PASS: windowed fullscreen does not pause wallpaper')
        finally:
            if preview:
                preview.stdin.close()
                await module.terminate(preview)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await control.command({'action': 'clear'})
            if original is not None:
                with contextlib.suppress(subprocess.CalledProcessError):
                    action('focus-window', original)


if __name__ == '__main__':
    asyncio.run(main())
