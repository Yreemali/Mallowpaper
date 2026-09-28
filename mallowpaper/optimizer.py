"""Bounded, cancellable FFmpeg playback-copy preparation. Originals are read-only."""
import asyncio
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


async def terminate(process):
    if process and process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def probe(path):
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,color_transfer:format=duration",
        "-of", "json", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 15)
        data = json.loads(stdout)
        if process.returncode or not data.get("streams"):
            raise ValueError("Could not probe video")
        stream = data["streams"][0]
        return stream, float(data.get("format", {}).get("duration", 0))
    finally:
        await terminate(process)


class Optimizer:
    def __init__(self, cache):
        self.cache = Path(cache)
        self.slot = asyncio.Semaphore(1)

    def prune(self, limit, protected):
        files = sorted(self.cache.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        size = sum(p.stat().st_size for p in files)
        for path in files:
            if size <= limit:
                break
            if str(path) not in protected:
                size -= path.stat().st_size
                path.unlink(missing_ok=True)
        return size

    async def prepare(self, source, fps, height, limit_mb, allowed, changed, protected, slow_fps=False):
        source = Path(source).resolve(strict=True)
        if not fps and not height:
            return str(source)
        info = source.stat()
        key = hashlib.sha256(f"{source}\0{info.st_size}\0{info.st_mtime_ns}\0{fps}\0{height}\0{int(slow_fps)}\0v2".encode()).hexdigest()
        target = self.cache / f"{key}.mp4"
        if target.is_file():
            target.touch()
            return str(target)
        changed("queued", 0)
        async with self.slot:
            if target.is_file():
                return str(target)
            while not allowed():
                changed("waiting_for_ac", 0)
                await asyncio.sleep(1)
            stream, duration = await probe(source)
            if duration <= 0:
                raise ValueError("Optimization needs a finite video duration")
            if stream.get("color_transfer") in ("smpte2084", "arib-std-b67"):
                raise ValueError("HDR optimization is not supported; use Source quality")
            filters = []
            expected_duration = duration
            if fps:
                try:
                    source_fps = float(Fraction(stream.get("avg_frame_rate", "0/1")))
                except (ValueError, ZeroDivisionError):
                    source_fps = 0
                if source_fps <= 0:
                    raise ValueError("Cannot determine source FPS; use Source FPS")
                if fps < source_fps:
                    if slow_fps:
                        # Give every source frame one output interval, including VFR
                        # inputs. An exact timebase avoids timestamp rounding drops.
                        ratio = source_fps / fps
                        filters.extend([f"settb=expr=1/{fps}", "setpts=N"])
                        expected_duration *= ratio
                    filters.append(f"fps={fps}")
            if height:
                width = height * 16 // 9
                if stream["width"] > width or stream["height"] > height:
                    filters.append(f"scale=w='min(iw,{width})':h='min(ih,{height})':force_original_aspect_ratio=decrease:force_divisible_by=2")
            if not filters:
                return str(source)
            filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
            self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            limit = limit_mb * 1024 * 1024
            protected_paths = protected()
            # Keep enough room for the new file without deleting any active player's copy.
            used = self.prune(limit // 2, protected_paths)
            budget = min(limit - used, shutil.disk_usage(self.cache).free - 128 * 1024 * 1024)
            if budget < 8 * 1024 * 1024:
                raise ValueError("Not enough free playback-cache space; clear unused copies or increase the limit")
            fd, temporary = tempfile.mkstemp(prefix="preparing-", suffix=".mp4", dir=self.cache)
            os.close(fd)
            process = None
            try:
                changed("preparing", 0)
                process = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                    "-threads", "1", "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
                    "-vf", ",".join(filters), "-filter_threads", "1", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23", "-threads", "1", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-progress", "pipe:1", "-stats_period", "0.5",
                    "-fs", str(budget), "-y", temporary,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                async with asyncio.timeout(1800):
                    while True:
                        if not allowed():
                            raise ValueError("Optimization stopped because AC power is unavailable; retry on AC")
                        try:
                            line = await asyncio.wait_for(process.stdout.readline(), 1)
                        except asyncio.TimeoutError:
                            continue
                        if not line:
                            break
                        text = line.decode().strip()
                        if text.startswith("out_time_us="):
                            try:
                                changed("preparing", min(99, int(int(text.split("=", 1)[1]) / expected_duration / 10000)))
                            except ValueError:
                                pass
                    await process.wait()
                if process.returncode:
                    raise ValueError("FFmpeg could not prepare this video")
                _, rendered_duration = await probe(temporary)
                if abs(rendered_duration - expected_duration) > max(0.2, 2 / (fps or 15)):
                    raise ValueError("Playback copy is incomplete (cache budget may be too small)")
                if Path(temporary).stat().st_size > budget:
                    raise ValueError("Playback copy exceeded its cache budget")
                if source.stat().st_mtime_ns != info.st_mtime_ns or source.stat().st_size != info.st_size:
                    raise ValueError("Source video changed during optimization; retry")
                os.replace(temporary, target)
                changed("ready", 100)
                return str(target)
            finally:
                await terminate(process)
                Path(temporary).unlink(missing_ok=True)
