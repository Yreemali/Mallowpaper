import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controller", ROOT / "mallowpaper/controller.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)

FAKE = '''#!/usr/bin/env python3
import json, sys
if "bad.mp4" in sys.argv[sys.argv.index("--file") + 1]:
    print(json.dumps({"version":1,"event":"error","message":"bad video"}), flush=True)
    sys.exit(3)
print(json.dumps({"version":1,"event":"ready"}), flush=True)
for line in sys.stdin:
    message=json.loads(line)
'''


class LifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.renderer = self.root / "renderer"
        self.renderer.write_text(FAKE)
        self.renderer.chmod(0o700)
        self.video = self.root / "video ' $ ü.mp4"
        self.video.touch()
        self.bad = self.root / "bad.mp4"
        self.bad.touch()
        self.events = []
        self.capture = patch.object(controller, "emit", lambda event, **data: self.events.append((event, data)))
        self.capture.start()
        self.control = controller.Controller(self.root / "state", str(self.renderer))
        await self.control.command({"action": "sync", "outputs": ["eDP-1", "DP-1"]})

    async def asyncTearDown(self):
        await asyncio.gather(*(player.stop() for player in tuple(self.control.children)))
        self.capture.stop()
        self.temp.cleanup()

    async def test_replacement_failure_preserves_old_video(self):
        await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.video)})
        old = self.control.players["eDP-1"]
        await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.bad)})
        self.assertIs(self.control.players["eDP-1"], old)
        self.assertIsNone(old.process.returncode)
        self.assertEqual(self.control.profiles["eDP-1"]["path"], str(self.video))
        self.assertIn("bad video", self.control.errors["eDP-1"])

    async def test_pause_persistence_hotplug_and_scale(self):
        await self.control.command({"action": "set", "output": "*", "path": str(self.video)})
        await self.control.command({"action": "pause", "output": "eDP-1", "paused": True})
        self.assertTrue(self.control.players["eDP-1"].paused)
        self.assertFalse(self.control.players["DP-1"].paused)
        await self.control.command({"action": "fit", "output": "eDP-1", "fit": "stretch"})
        await self.control.command({"action": "sync", "outputs": ["DP-1"], "fit": "fit"})
        self.assertNotIn("eDP-1", self.control.players)
        self.assertIn("eDP-1", self.control.profiles)
        await self.control.command({"action": "sync", "outputs": ["DP-1", "eDP-1"], "fit": "fit"})
        self.assertTrue(self.control.players["eDP-1"].paused)
        self.assertEqual(self.control.players["eDP-1"].profile["fit"], "stretch")
        saved = controller.Controller(self.root / "state", str(self.renderer))
        self.assertEqual(saved.profiles, self.control.profiles)
        await self.control.command({"action": "clear", "output": "DP-1"})
        self.assertNotIn("DP-1", self.control.players)
        self.assertNotIn("DP-1", self.control.profiles)
        self.assertIn("eDP-1", self.control.profiles)

    async def test_crash_reports_static_fallback(self):
        await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.video)})
        player = self.control.players["eDP-1"]
        player.process.kill()
        await player.reader
        self.assertNotIn("eDP-1", self.control.players)
        self.assertIn("eDP-1", self.control.profiles)
        self.assertEqual(self.events[-1][1]["active"], {})

    async def test_write_failure_preserves_previous_renderer(self):
        await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.video)})
        old = self.control.players["eDP-1"]
        with patch.object(self.control, "persist", side_effect=OSError("disk full")):
            await self.control.command({"action": "fit", "output": "eDP-1", "fit": "fit"})
        self.assertIn("disk full", self.control.errors["eDP-1"])
        self.assertIs(self.control.players["eDP-1"], old)
        self.assertEqual(len(self.control.children), 1)

    async def test_socket_protocol_and_shutdown(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}):
            task = asyncio.create_task(self.control.serve())
            path = controller.socket_path(self.root / "state")
            for _ in range(50):
                if task.done():
                    await task
                if path.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            async def send(message):
                reader, writer = await asyncio.open_unix_connection(path)
                writer.write((json.dumps(message) + "\n").encode())
                await writer.drain()
                data = json.loads(await reader.readline())
                writer.close()
                await writer.wait_closed()
                return data
            self.assertFalse((await send({"version": 2}))["ok"])
            self.assertTrue((await send({"version": 1, "action": "shutdown"}))["ok"])
            await asyncio.wait_for(task, 4)
            self.assertFalse(path.exists())

    async def test_library_filters_directories_and_unrelated_files(self):
        (self.root / "fake.mp4").mkdir()
        (self.root / "image.PNG").touch()
        names = [item["name"] for item in controller.library(self.root)["items"]]
        self.assertIn(self.video.name, names)
        self.assertIn("image.PNG", names)
        self.assertNotIn("fake.mp4", names)
        self.assertNotIn("renderer", names)

    async def test_automatic_reasons_do_not_override_manual_pause(self):
        await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.video)})
        player = self.control.players["eDP-1"]
        self.control.config["pause_battery"] = True
        self.control.environment = {"power_available": True, "on_battery": True, "percentage": 10}
        await self.control.update_policy()
        self.assertEqual(player.reasons, {"battery", "low_battery"})
        await self.control.command({"action": "pause", "output": "eDP-1", "paused": True})
        self.control.environment["on_battery"] = False
        await self.control.update_policy()
        self.assertEqual(player.reasons, {"manual"})
        await self.control.command({"action": "pause", "output": "eDP-1", "paused": False})
        self.assertFalse(player.paused)

    async def test_cancel_preparation_keeps_playing_and_controls_responsive(self):
        await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.video)})
        player = self.control.players["eDP-1"]
        self.control.config["optimize"] = True
        self.control.config["slow_fps"] = True
        entered = asyncio.Event()
        async def slow(*args, **kwargs):
            self.assertTrue(kwargs["slow_fps"])
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.control.optimizer, "prepare", side_effect=slow):
            await self.control.command({"action": "set", "output": "eDP-1", "path": str(self.bad)}, wait=False)
            await asyncio.wait_for(entered.wait(), 1)
            await self.control.command({"action": "policy", "output": "eDP-1",
                                        "values": {"pause_battery": True}})
            self.assertEqual(self.control.profiles["eDP-1"]["path"], str(self.video))
            self.assertEqual(player.profile["path"], str(self.video))
            self.assertEqual(self.control.pending_profiles["eDP-1"]["path"], str(self.bad))
            self.assertTrue(player.profile["pause_battery"])
            await self.control.command({"action": "pause", "output": "eDP-1", "paused": True})
            self.assertTrue(player.paused)
            await self.control.command({"action": "cancel", "output": "eDP-1"})
        self.assertIs(self.control.players["eDP-1"], player)
        self.assertFalse(self.control.jobs)
        self.assertFalse(self.control.pending_profiles)


if __name__ == "__main__":
    unittest.main()
