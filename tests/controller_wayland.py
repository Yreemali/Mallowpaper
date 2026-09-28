"""Temporary live Niri test of the controller with the real Qt renderer."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controller", ROOT / "vwallpaper/controller.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


async def main():
    output = next(iter(json.loads(subprocess.check_output(["niri", "msg", "-j", "outputs"]))))
    os.environ["QT_QPA_PLATFORM"] = "wayland"
    local_plugins = ROOT / ".deps/layer-shell-qt/usr/lib/qt6/plugins"
    if local_plugins.exists():
        os.environ["QT_PLUGIN_PATH"] = str(local_plugins)
    with tempfile.TemporaryDirectory(prefix="vwallpaper-controller-live-") as directory:
        root = Path(directory)
        clip = root / "clip.mp4"
        bad = root / "broken.mp4"
        bad.write_bytes(b"not video")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=640x360:rate=24", "-t", "1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        control = module.Controller(root / "state", str(ROOT / "build/vwallpaper-renderer"))
        try:
            await control.command({"action": "sync", "outputs": [output]})
            await control.command({"action": "set", "output": output, "path": str(clip)})
            assert output in control.players, control.errors
            old = control.players[output]
            await control.command({"action": "pause", "output": output, "paused": True})
            assert old.paused
            await control.command({"action": "set", "output": output, "path": str(bad)})
            assert control.players[output] is old and old.process.returncode is None
            await control.command({"action": "fit", "output": output, "fit": "fit"})
            assert control.players[output] is not old and old.process.returncode == 0
            assert control.players[output].paused
            await control.command({"action": "clear", "output": output})
            assert not control.players and not control.children
            print("PASS: real Qt startup, pause, failed replacement rollback, scale replacement, cleanup")
        finally:
            await asyncio.gather(*(player.stop() for player in tuple(control.children)))


if __name__ == "__main__":
    asyncio.run(main())
