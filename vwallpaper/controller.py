#!/usr/bin/env python3
"""Private local controller for Noctalia's streamed-process API (stdlib only)."""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile

# Also support loading this module directly from the integration tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from policies import NiriState, pause_reasons, settings
from optimizer import Optimizer, terminate

VERSION = 1
VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
FITS = {"fill", "fit", "stretch"}
_output_closed = False


def emit(event, **values):
    global _output_closed
    if _output_closed:
        return False
    try:
        print(json.dumps({"version": VERSION, "event": event, **values}), flush=True)
        return True
    except BrokenPipeError:
        _output_closed = True
        sys.stdout = open(os.devnull, "w")
        return False


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".state-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def socket_path(state_dir):
    base = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    token = hashlib.sha256(str(Path(state_dir).resolve()).encode()).hexdigest()[:16]
    directory = base / f"vwallpaper-{os.getuid()}-{token}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Controller runtime directory must be private and owned by this user")
    return directory / "control.sock"


def library(directory):
    root = Path(directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Wallpaper directory is not a directory")
    items = []
    # Bounded scan; sorting only accepted files keeps non-media directories cheap.
    with os.scandir(root) as entries:
        for entry in entries:
            suffix = Path(entry.name).suffix.lower()
            if suffix not in VIDEO | IMAGE or not entry.is_file():
                continue
            items.append({"name": entry.name, "path": str(root / entry.name),
                          "kind": "video" if suffix in VIDEO else "image"})
            if len(items) >= 4096:
                break
    items.sort(key=lambda item: item["name"].casefold())
    return {"items": items, "limited": len(items) == 4096}


def thumbnail(path, cache):
    source = Path(path).resolve(strict=True)
    info = source.stat()
    if not source.is_file() or source.suffix.lower() not in VIDEO | IMAGE:
        raise ValueError("Unsupported media file")
    key = hashlib.sha256(f"{source}\0{info.st_size}\0{info.st_mtime_ns}\0v1".encode()).hexdigest()
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = cache / f"{key}.jpg"
    if not target.exists():
        fd, temporary = tempfile.mkstemp(suffix=".jpg", dir=cache)
        os.close(fd)
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1",
                            "-i", str(source), "-frames:v", "1", "-vf",
                            "scale=320:180:force_original_aspect_ratio=decrease",
                            "-filter_threads", "1", "-threads", "1", "-q:v", "4", "-y", temporary],
                           check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    # Bounded cache, oldest first. This worker only runs for requested thumbnails.
    files = sorted(cache.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for old in files:
        if total <= 128 * 1024 * 1024:
            break
        if old != target:
            total -= old.stat().st_size
            old.unlink(missing_ok=True)
    return {"path": str(target)}


class Player:
    def __init__(self, owner, output, profile):
        self.owner, self.output, self.profile = owner, output, profile
        self.playback_path = profile["path"]
        self.process = None
        self.ready = asyncio.get_running_loop().create_future()
        self.reader = None
        self.stopping = False
        self.paused = None
        self.reasons = set()

    async def start(self):
        self.owner.children.add(self)
        self.reasons = self.owner.reasons_for(self.output, self.profile)
        argv = [self.owner.renderer, "--output", self.output, "--file", self.playback_path,
                "--fit", self.profile.get("fit", self.owner.fit)]
        for reason in sorted(self.reasons):
            argv.extend(["--pause-reason", reason])
        self.process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        self.reader = asyncio.create_task(self.read())
        await asyncio.wait_for(asyncio.shield(self.ready), 18)
        self.paused = bool(self.reasons)
        await self.set_reasons(self.owner.reasons_for(self.output, self.profile))

    async def read(self):
        error = "Renderer exited unexpectedly"
        try:
            async for line in self.process.stdout:
                data = json.loads(line)
                if data.get("version") != VERSION:
                    raise ValueError("Incompatible renderer protocol")
                if data.get("event") == "ready" and not self.ready.done():
                    self.ready.set_result(True)
                elif data.get("event") == "error":
                    error = data.get("message", "Playback failed")
        except (ValueError, asyncio.LimitOverrunError) as exc:
            error = str(exc)
        finally:
            await self.process.wait()
            if not self.ready.done():
                self.ready.set_exception(RuntimeError(error))
            if not self.stopping and self.owner.players.get(self.output) is self:
                self.owner.players.pop(self.output, None)
                self.owner.errors[self.output] = error
                self.owner.publish()
            self.owner.children.discard(self)

    async def pause(self, value):
        self.profile["paused"] = value
        await self.set_reasons(self.owner.reasons_for(self.output, self.profile))

    async def set_reasons(self, reasons):
        if self.reasons == reasons:
            return False
        if self.process.returncode is not None:
            raise RuntimeError("Renderer is no longer running")
        # Add before removing, so switching between two reasons never briefly resumes.
        changes = [("pause", reason) for reason in sorted(reasons - self.reasons)]
        changes += [("resume", reason) for reason in sorted(self.reasons - reasons)]
        for command, reason in changes:
            self.process.stdin.write((json.dumps({"version": VERSION,
                "command": command, "reason": reason}) + "\n").encode())
        await self.process.stdin.drain()
        self.reasons = set(reasons)
        self.paused = bool(reasons)
        return True

    async def stop(self):
        self.stopping = True
        if not self.process:
            self.owner.children.discard(self)
            return
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            await self.reader
        if self.ready.done() and not self.ready.cancelled():
            self.ready.exception()  # Retrieve a startup failure even on cancellation.
        self.owner.children.discard(self)


class Controller:
    def __init__(self, state_dir, renderer):
        self.state_file = Path(state_dir) / "assignments.json"
        self.renderer = renderer
        self.profiles, self.players, self.errors = {}, {}, {}
        self.children = set()
        self.outputs = set()
        self.fit = "fill"
        self.config = settings({})
        self.environment = {}
        self.niri = NiriState()
        self.policy_dirty = asyncio.Event()
        self.jobs, self.pending_profiles, self.preparation = {}, {}, {}
        self.optimizer = Optimizer(self.state_file.parent / "playback-cache")
        self.queue = asyncio.Queue(maxsize=64)
        self.stopped = asyncio.Event()
        if self.state_file.exists():
            saved = json.loads(self.state_file.read_text())
            if saved.get("version") != VERSION or not isinstance(saved.get("profiles"), dict):
                raise ValueError("Unsupported assignments file; refusing to overwrite it")
            for output, profile in saved["profiles"].items():
                if not isinstance(profile, dict) or not isinstance(profile.get("path"), str):
                    raise ValueError("Invalid saved assignment")
                if "fit" in profile and profile["fit"] not in FITS:
                    raise ValueError("Invalid saved scale mode")
                settings({key: value for key, value in profile.items() if key in self.config})
                if "paused" in profile and not isinstance(profile["paused"], bool):
                    raise ValueError("Invalid saved pause state")
                self.profiles[output] = profile

    def persist(self):
        atomic_json(self.state_file, {"version": VERSION, "profiles": self.profiles})

    def publish(self):
        emit("state", profiles=self.profiles, active={output: {
            "path": player.profile["path"], "paused": player.paused,
            "manual_paused": player.profile.get("paused", False),
            "pause_reasons": sorted(player.reasons),
            "optimized": player.playback_path != player.profile["path"],
            "fit": player.profile.get("fit", self.fit)} for output, player in self.players.items()},
            errors=self.errors, preparation=self.preparation,
            capabilities={"power": self.environment.get("power_available", False),
                          "session": self.environment.get("session_available", False),
                          "fullscreen": self.niri.connected and self.environment.get("foreign_available", False)})

    def reasons_for(self, output, profile):
        fullscreen = self.niri.fullscreen_outputs(self.environment, self.config["fullscreen_focused"])
        return pause_reasons(output, profile, self.config, self.environment, fullscreen)

    def can_optimize(self):
        return not self.environment.get("sleeping") and (not self.config["ac_only"] or
            (self.environment.get("power_available") and not self.environment.get("on_battery")))

    async def cancel_job(self, output):
        task = self.jobs.get(output)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def assign(self, output, profile, wait=True):
        await self.cancel_job(output)
        self.pending_profiles[output] = profile
        self.errors.pop(output, None)
        async def run():
            try:
                return await self.replace(output, profile)
            except (OSError, ValueError, RuntimeError, asyncio.TimeoutError) as exc:
                self.errors[output] = str(exc) or "Preparation timed out"
                return False
            finally:
                self.jobs.pop(output, None)
                self.pending_profiles.pop(output, None)
                self.preparation.pop(output, None)
                self.publish()
        task = asyncio.create_task(run())
        self.jobs[output] = task
        if wait:
            return await task

    async def replace(self, output, profile):
        candidate = Player(self, output, profile)
        try:
            if self.config["optimize"]:
                def progress(stage, percent):
                    current = {"stage": stage, "percent": percent}
                    if self.preparation.get(output) != current:
                        self.preparation[output] = current
                        self.publish()
                candidate.playback_path = await self.optimizer.prepare(profile["path"],
                    profile.get("fps", self.config["fps"]), profile.get("height", self.config["height"]),
                    self.config["cache_mb"], self.can_optimize, progress,
                    lambda: {player.playback_path for player in self.children},
                    slow_fps=self.config["slow_fps"])
            await candidate.start()
            if candidate.process.returncode is not None:
                raise RuntimeError("Renderer exited during startup")
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, BrokenPipeError) as exc:
            await candidate.stop()
            self.errors[output] = str(exc) or "Renderer startup timed out"
            self.publish()
            return False
        except asyncio.CancelledError:
            await candidate.stop()
            raise
        previous = self.players.get(output)
        old_profile = self.profiles.get(output)
        self.profiles[output] = dict(profile)
        try:
            self.persist()
        except OSError:
            if old_profile is None:
                self.profiles.pop(output, None)
            else:
                self.profiles[output] = old_profile
            await candidate.stop()
            raise
        self.players[output] = candidate
        self.errors.pop(output, None)
        self.publish()  # The Noctalia service hides its static surface only now.
        if previous:
            await previous.stop()
        return True

    async def stop_output(self, output):
        await self.cancel_job(output)
        previous = self.players.pop(output, None)
        if previous:
            await previous.stop()

    async def command(self, data, wait=True):
        action = data.get("action")
        if action == "sync":
            outputs = data.get("outputs")
            if outputs == {}:  # Luau encodes an empty table as an object.
                outputs = []
            if not isinstance(outputs, list) or not all(isinstance(o, str) for o in outputs):
                raise ValueError("Invalid outputs")
            fit = data.get("fit", "fill")
            if fit not in FITS:
                raise ValueError("Invalid default scale mode")
            old_fit, self.fit = self.fit, fit
            old_config = self.config
            self.config = settings(data.get("settings", self.config))
            self.outputs = set(outputs)
            for output in set(self.players) | set(self.jobs):
                if output not in self.outputs:
                    await self.stop_output(output)
            for output in self.outputs:
                profile = self.profiles.get(output)
                if profile and (output not in self.players or old_config != self.config or (old_fit != fit and "fit" not in profile)):
                    await self.assign(output, dict(profile), wait)
            await self.query_outputs()
            self.policy_dirty.set()
            self.publish()
            return
        target = data.get("output", "*")
        if not isinstance(target, str):
            raise ValueError("Output must be a connector name")
        targets = sorted(self.outputs) if target == "*" else [target]
        if any(o not in self.outputs for o in targets):
            raise ValueError("Output is disconnected")
        if action == "set":
            if not isinstance(data.get("path"), str):
                raise ValueError("Path must be a string")
            path = Path(data["path"]).expanduser().resolve(strict=True)
            if not path.is_file() or path.suffix.lower() not in VIDEO:
                raise ValueError("Select a supported local video")
            for output in targets:
                profile = dict(self.pending_profiles.get(output, self.profiles.get(output, {})), path=str(path))
                await self.assign(output, profile, wait)
        elif action == "clear":
            for output in targets:
                await self.stop_output(output)
                self.profiles.pop(output, None)
                self.errors.pop(output, None)
            self.persist()
        elif action == "pause":
            paused = data.get("paused")
            if not isinstance(paused, bool):
                raise ValueError("paused must be a boolean")
            for output in targets:
                if output in self.profiles:
                    self.profiles[output]["paused"] = paused
                if output in self.pending_profiles:
                    self.pending_profiles[output]["paused"] = paused
                if output in self.players:
                    await self.players[output].pause(paused)
            self.persist()
        elif action in ("fit", "quality", "policy"):
            changes = {"fit": data.get("fit")} if action == "fit" else data.get("values", {})
            if not isinstance(changes, dict):
                raise ValueError("Overrides must be an object")
            for key, value in changes.items():
                allowed = {"fit": ("fit",), "quality": ("fps", "height"),
                           "policy": ("pause_battery", "pause_fullscreen")}
                if key not in allowed[action]:
                    raise ValueError("Unsupported output override")
                if value == "inherit":
                    continue
                if key == "fit":
                    if value not in FITS:
                        raise ValueError("Invalid scale mode")
                else:
                    changes[key] = settings({key: value})[key]
            for output in targets:
                existing = self.pending_profiles.get(output, self.profiles.get(output))
                if existing:
                    profile = dict(existing)
                    for key, value in changes.items():
                        if value == "inherit":
                            profile.pop(key, None)
                        else:
                            profile[key] = value
                    if action == "policy":
                        profiles = [self.pending_profiles.get(output), self.profiles.get(output)]
                        if output in self.players:
                            profiles.append(self.players[output].profile)
                        for current in profiles:
                            if current is None:
                                continue
                            for key, value in changes.items():
                                if value == "inherit":
                                    current.pop(key, None)
                                else:
                                    current[key] = value
                    else:
                        await self.assign(output, profile, wait)
            if action == "policy":
                self.persist()
                await self.update_policy()
        elif action == "cancel":
            for output in targets:
                await self.cancel_job(output)
        else:
            raise ValueError("Unknown action")
        self.publish()

    async def worker(self):
        while True:
            data = await self.queue.get()
            try:
                await self.command(data, wait=False)
                emit("completed", request=data.get("request"), action=data.get("action"))
            except (ValueError, OSError, RuntimeError, TypeError) as exc:
                emit("error", message=str(exc), request=data.get("request"))
            finally:
                self.queue.task_done()

    async def query_outputs(self):
        path = os.environ.get("NIRI_SOCKET")
        if not path:
            return
        writer = None
        try:
            async with asyncio.timeout(3):
                reader, writer = await asyncio.open_unix_connection(path, limit=4 * 1024 * 1024)
                writer.write(b'"Outputs"\n')
                await writer.drain()
                reply = json.loads(await reader.readline())
                self.niri.outputs = reply["Ok"]["Outputs"]
        except (OSError, ValueError, KeyError, asyncio.TimeoutError):
            self.niri.outputs = {}
        finally:
            if writer:
                writer.close()

    async def watch_niri(self):
        delay = 1
        while True:
            writer = None
            try:
                path = os.environ.get("NIRI_SOCKET")
                if not path:
                    return
                reader, writer = await asyncio.open_unix_connection(path, limit=4 * 1024 * 1024)
                self.niri.windows.clear()
                self.niri.workspaces.clear()
                self.niri.overview = False
                await self.query_outputs()
                writer.write(b'"EventStream"\n')
                await writer.drain()
                reply = json.loads(await asyncio.wait_for(reader.readline(), 3))
                if "Ok" not in reply:
                    raise ValueError("Niri event subscription rejected")
                self.niri.connected = True
                self.policy_dirty.set()
                delay = 1
                async for line in reader:
                    message = json.loads(line)
                    if "ConfigLoaded" in message:
                        await self.query_outputs()
                    if self.niri.consume(message):
                        self.policy_dirty.set()
            except (OSError, ValueError, KeyError, asyncio.TimeoutError):
                pass
            finally:
                self.niri.connected = False
                self.policy_dirty.set()
                if writer:
                    writer.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def watch_environment(self):
        executable = str(Path(self.renderer).resolve().with_name("vwallpaper-monitor"))
        delay = 1
        while True:
            process = None
            try:
                process = await asyncio.create_subprocess_exec(executable,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4 * 1024 * 1024)
                async for line in process.stdout:
                    snapshot = json.loads(line)
                    if snapshot.get("version") == 1 and snapshot.get("event") == "environment":
                        self.environment = snapshot
                        self.policy_dirty.set()
                        delay = 1
            except (OSError, ValueError):
                pass
            finally:
                await terminate(process)
                self.environment = {}
                self.policy_dirty.set()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def update_policy(self):
        changed = False
        for output, player in list(self.players.items()):
            try:
                changed = await player.set_reasons(self.reasons_for(output, player.profile)) or changed
            except (OSError, RuntimeError):
                # The reader handles process death and publishes the static fallback.
                pass
        return changed

    async def policy_loop(self):
        capabilities = None
        while True:
            await self.policy_dirty.wait()
            self.policy_dirty.clear()
            await asyncio.sleep(0.1)  # Coalesce window/workspace and Wayland state updates.
            current = (self.niri.connected, self.environment.get("foreign_available"),
                       self.environment.get("power_available"), self.environment.get("session_available"))
            if await self.update_policy() or current != capabilities:
                capabilities = current
                self.publish()

    async def accept(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), 3)
            data = json.loads(line)
            if not isinstance(data, dict) or data.get("version") != VERSION:
                raise ValueError("Incompatible controller protocol")
            if data.get("action") == "shutdown":
                self.stopped.set()
            elif data.get("action") == "status":
                self.publish()
            else:
                self.queue.put_nowait(data)
            response = {"ok": True}
        except (ValueError, asyncio.TimeoutError, asyncio.QueueFull) as exc:
            response = {"ok": False, "error": str(exc)}
        writer.write((json.dumps(response) + "\n").encode())
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()

    async def heartbeat(self):
        while True:
            if emit("heartbeat") is False:
                self.stopped.set()  # Noctalia disappeared; release all owned renderers.
                return
            await asyncio.sleep(5)

    async def serve(self):
        path = socket_path(self.state_file.parent)
        with open(path.with_suffix(".lock"), "w") as lock:
            for attempt in range(31):
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if attempt == 30:
                        raise RuntimeError("Another controller still owns this plugin session")
                    await asyncio.sleep(0.1)
            path.unlink(missing_ok=True)  # Only the lock owner may remove a stale socket.
            server = await asyncio.start_unix_server(self.accept, path=path, limit=65536)
            os.chmod(path, 0o600)
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self.stopped.set)
            tasks = [asyncio.create_task(coro) for coro in (self.worker(), self.heartbeat(),
                self.watch_niri(), self.watch_environment(), self.policy_loop())]
            emit("online")
            self.publish()
            try:
                await self.stopped.wait()
            finally:
                server.close()
                await server.wait_closed()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for output in list(self.jobs):
                    await self.cancel_job(output)
                await asyncio.gather(*(player.stop() for player in tuple(self.children)))
                self.players.clear()
                self.publish()
                path.unlink(missing_ok=True)
                emit("offline")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--state-dir", required=True)
    serve.add_argument("--renderer", required=True)
    send = sub.add_parser("send")
    send.add_argument("--state-dir", required=True)
    send.add_argument("message")
    scan = sub.add_parser("scan")
    scan.add_argument("directory")
    thumb = sub.add_parser("thumbnail")
    thumb.add_argument("path")
    thumb.add_argument("cache")
    args = parser.parse_args()
    try:
        if args.mode == "serve":
            asyncio.run(Controller(args.state_dir, args.renderer).serve())
        elif args.mode == "send":
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(4)
                client.connect(str(socket_path(args.state_dir)))
                message = json.loads(args.message)
                message["version"] = VERSION
                client.sendall((json.dumps(message) + "\n").encode())
                result = json.loads(client.makefile("rb").readline(65536))
                print(json.dumps(result))
                return 0 if result["ok"] else 1
        elif args.mode == "scan":
            print(json.dumps(library(args.directory)))
        else:
            print(json.dumps(thumbnail(args.path, args.cache)))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        emit("error", message=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
