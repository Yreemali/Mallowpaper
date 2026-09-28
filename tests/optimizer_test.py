import asyncio
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mallowpaper"))
from optimizer import Optimizer, probe


class OptimizerTest(unittest.IsolatedAsyncioTestCase):
    async def test_effective_caps_cache_and_original_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video ' $ ü.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1600x900:rate=30", "-t", "1.6", "-c:v", "libx264",
                "-threads", "1", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source)], check=True)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            optimizer = Optimizer(root / "cache")
            events = []
            args = (source, 15, 720, 128, lambda: True, lambda *event: events.append(event), lambda: set())
            result = await optimizer.prepare(*args)
            stream, duration = await probe(result)
            self.assertEqual((stream["width"], stream["height"]), (1280, 720))
            self.assertEqual(stream["avg_frame_rate"], "15/1")
            self.assertAlmostEqual(duration, 1.6, delta=0.14)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            self.assertEqual(events[-1], ("ready", 100))
            with patch("optimizer.probe", side_effect=AssertionError("Cache hit must not decode/probe")):
                self.assertEqual(await optimizer.prepare(*args), result)
            slow_result = await optimizer.prepare(*args, slow_fps=True)
            self.assertNotEqual(slow_result, result)
            slow_stream, slow_duration = await probe(slow_result)
            self.assertEqual(slow_stream["avg_frame_rate"], "15/1")
            self.assertAlmostEqual(slow_duration, 3.2, delta=0.14)
            def count_frames(path):
                return int(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)]))
            self.assertEqual(count_frames(slow_result), count_frames(source))
            with patch("optimizer.probe", side_effect=AssertionError("Slow-motion cache hit must not probe")):
                self.assertEqual(await optimizer.prepare(*args, slow_fps=True), slow_result)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            self.assertEqual(await optimizer.prepare(source, 60, 2160, 128, lambda: True,
                lambda *_: None, lambda: set(), slow_fps=True), str(source))
            self.assertEqual(await optimizer.prepare(source, 60, 2160, 128, lambda: True, lambda *_: None, lambda: set()), str(source))

    async def test_cancel_waiting_does_not_leave_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.mp4"
            source.touch()
            optimizer = Optimizer(Path(directory) / "cache")
            seen = asyncio.Event()
            task = asyncio.create_task(optimizer.prepare(source, 15, 720, 128, lambda: False,
                lambda *_: seen.set(), lambda: set()))
            await asyncio.wait_for(seen.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(list(Path(directory).rglob("preparing-*")))


if __name__ == "__main__":
    unittest.main()
