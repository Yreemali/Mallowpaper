"""Exercise real decoding and IPC without touching the desktop wallpaper."""
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
    binary = str(Path(sys.argv[1]).resolve())
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QSG_RHI_BACKEND="opengl",
               QT_QUICK_BACKEND="software", QT_MEDIA_BACKEND="ffmpeg",
               QT_QPA_PLATFORMTHEME="", QT_STYLE_OVERRIDE="Basic")
    with tempfile.TemporaryDirectory(prefix="mallowpaper-test-") as directory:
        video = Path(directory) / "video space ' $ test.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x180:rate=15", "-t", "1", "-c:v",
                        "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
        with open(Path(directory) / "stderr.log", "w+") as log:
            process = subprocess.Popen([binary, "--preview", "--file", str(video),
                                        "--pause-reason", "manual"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=log, text=True, env=env)
            events = queue.Queue()

            def read():
                for line in process.stdout:
                    events.put(json.loads(line))
                events.put({"event": "eof"})

            threading.Thread(target=read, daemon=True).start()

            def receive(kind):
                deadline = time.monotonic() + 18
                while time.monotonic() < deadline:
                    event = events.get(timeout=max(0.1, deadline - time.monotonic()))
                    assert event["event"] != "eof", "renderer exited unexpectedly"
                    assert event["event"] != "error" or kind == "error", event
                    if event["event"] == kind:
                        assert event["version"] == 1
                        return event
                raise AssertionError(f"timed out waiting for {kind}")

            def command(name, reason=None):
                message = {"version": 1, "command": name}
                if reason:
                    message["reason"] = reason
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()

            try:
                receive("ready")
                initial = receive("status")
                assert initial["ready"] and not initial["playing"]
                assert initial["pause_reasons"] == ["manual"]
                time.sleep(0.3)
                command("status")
                paused_start = receive("status")
                time.sleep(0.5)
                command("status")
                assert receive("status")["frames"] == paused_start["frames"]
                command("resume", "manual")
                assert receive("status")["playing"]
                time.sleep(2.3)  # Cross two loop boundaries.
                command("status")
                assert receive("status")["frames"] > 25
                command("pause", "manual")
                assert receive("status")["pause_reasons"] == ["manual"]
                command("pause", "fullscreen")
                assert receive("status")["pause_reasons"] == ["fullscreen", "manual"]
                command("resume", "fullscreen")
                assert not receive("status")["playing"]
                time.sleep(0.3)  # Let queued frames settle.
                command("status")
                paused = receive("status")
                time.sleep(0.5)
                command("status")
                later = receive("status")
                assert later["frames"] == paused["frames"], (paused, later)
                assert later["position_ms"] == paused["position_ms"]
                command("resume", "manual")
                assert receive("status")["playing"]
                command("pause", "invalid")
                receive("error")
                process.stdin.write('{"version":2,"command":"quit"}\nnot json\n')
                process.stdin.flush()
                receive("error")
                receive("error")
                command("status")
                assert receive("status")["playing"]
                process.stdin.close()  # Parent disappearance must release the helper.
                assert process.wait(timeout=5) == 0
                receive("stopped")
            except BaseException:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

        for extra in (["--file", str(video), "--fit", "bad"],
                      ["--file", str(video), "--output", "missing"],
                      ["--file", str(Path(directory) / "missing")]):
            result = subprocess.run([binary, "--preview", *extra], env=env,
                                    capture_output=True, text=True, timeout=5)
            assert result.returncode == 2, result
            assert json.loads(result.stdout)["event"] == "error"
        corrupt = Path(directory) / "corrupt.mp4"
        corrupt.write_bytes(b"not a video")
        process = subprocess.Popen([binary, "--preview", "--file", str(corrupt)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, env=env)
        try:
            # Keep stdin open so a clean EOF exit cannot mask a decoder error.
            assert process.wait(timeout=5) == 3
            assert any(json.loads(line)["event"] == "error" for line in process.stdout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdin.close()
    print("PASS: decode, loop, independent pause reasons, resume, IPC validation, EOF, invalid arguments")


if __name__ == "__main__":
    main()
