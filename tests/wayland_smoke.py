"""Briefly map the prototype on Niri, verify its layer, then remove it.

Does not change Noctalia settings or stop any existing wallpaper renderer.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time


def main():
    root = Path(__file__).resolve().parents[1]
    binary = root / "build/vwallpaper-renderer"
    env = dict(os.environ, QT_QPA_PLATFORM="wayland", QT_QPA_PLATFORMTHEME="")
    local_plugins = root / ".deps/layer-shell-qt/usr/lib/qt6/plugins"
    if local_plugins.exists():
        env["QT_PLUGIN_PATH"] = str(local_plugins)
    listed = subprocess.run([binary, "--list-outputs"], env=env, capture_output=True,
                            text=True, check=True, timeout=5)
    outputs = json.loads(listed.stdout)["outputs"]
    output = sys.argv[1] if len(sys.argv) > 1 else outputs[0]["name"]
    with tempfile.TemporaryDirectory(prefix="vwallpaper-wayland-") as directory:
        video = Path(directory) / "sample.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=640x360:rate=30", "-t", "1", "-c:v",
                        "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
        with open(Path(directory) / "stderr.log", "w+") as log:
            process = subprocess.Popen([binary, "--output", output, "--file", video],
                                       env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=log, text=True)
            events = queue.Queue()

            def read():
                for line in process.stdout:
                    events.put(json.loads(line))
                events.put({"event": "eof"})

            threading.Thread(target=read, daemon=True).start()

            def receive(kind):
                while True:
                    event = events.get(timeout=18)
                    assert event["event"] not in ("error", "eof"), event
                    if event["event"] == kind:
                        return event

            def command(name):
                process.stdin.write(json.dumps({"version": 1, "command": name,
                                                "reason": "manual"}) + "\n")
                process.stdin.flush()
                return receive("status")

            def ticks():
                # comm may contain spaces; fields after the final ')' start at field 3.
                fields = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()
                return int(fields[11]) + int(fields[12])

            try:
                receive("ready")
                receive("status")
                layers = json.loads(subprocess.check_output(["niri", "msg", "-j", "layers"], text=True))
                assert any(layer["namespace"] == "vwallpaper" and layer["output"] == output
                           and layer["layer"] == "Background"
                           and layer["keyboard_interactivity"] == "None" for layer in layers), layers
                time.sleep(1.2)
                playing = command("status")
                assert playing["frames"] >= 25, playing
                assert not command("pause")["playing"]
                time.sleep(0.3)
                before = command("status")
                start_ticks = ticks()
                time.sleep(1)
                paused_ticks = ticks() - start_ticks
                after = command("status")
                assert before["frames"] == after["frames"], (before, after)
                assert command("resume")["playing"]
                time.sleep(0.3)
                assert command("status")["frames"] > after["frames"]
                process.stdin.close()
                assert process.wait(timeout=5) == 0
                layers = json.loads(subprocess.check_output(["niri", "msg", "-j", "layers"], text=True))
                assert not any(layer["namespace"] == "vwallpaper" for layer in layers), layers
                print(json.dumps({"result": "PASS", "output": output,
                                  "playing_frames": playing["frames"],
                                  "paused_frames": after["frames"] - before["frames"],
                                  "paused_cpu_ticks_over_1s": paused_ticks,
                                  "clock_ticks_per_second": os.sysconf("SC_CLK_TCK")}))
                log.seek(0)
                print(log.read(), file=sys.stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
