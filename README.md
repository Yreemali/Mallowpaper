# Video wallpaper for Noctalia

An early Qt Multimedia / FFmpeg video wallpaper plugin targeting Noctalia 5.1.x and Niri.
The renderer, native picker, bar widget, and playback service are implemented.
Automatic power/fullscreen policies and opt-in FPS/resolution optimization are implemented.
Release validation on physical multi-monitor and low-end hardware remains pending.
See [PLAN.md](PLAN.md) for the full feature scope.

## Implemented

- A real Wayland background layer surface on an explicitly selected output.
- Silent looping video through Qt Multimedia and Qt Quick VideoOutput.
- Fill/crop, fit, and stretch placement.
- Versioned JSON-line commands and events.
- Independent pause reasons: clearing fullscreen pause cannot clear manual pause.
- First-frame readiness, decode errors, startup timeout, output removal handling,
  and cleanup when the controlling process closes stdin.
- Ordinary-window preview and headless integration tests.
- Native Noctalia picker with search, image/video filters, output selection,
  cached thumbnails, pagination, pause/resume, and restore controls.
- Configurable wallpaper directory and default scale, with per-output scale overrides.
- A private socket controller that owns renderer processes, atomically saves video
  assignments/manual pause/scale, and retains profiles across output disconnections.
- Replacement handoff after first-frame readiness; a bad replacement keeps the old
  video. Renderer failure restores the static wallpaper through the Noctalia service.
- Battery, low-battery, logind lock/inactive-session, and suspend pause policies.
- Conservative Niri fullscreen detection per active output workspace; optional
  focused-display-only behavior and per-output battery/fullscreen overrides.
- Opt-in playback copies with effective FPS/resolution caps, one FFmpeg job at a
  time, bounded cache, AC-only preparation, progress, and cancellation.
- Wallpaper bar icon: click opens the picker, middle click pauses/resumes its output,
  right click opens plugin settings. Noctalia's configurable gestures still apply.

The controller owns one renderer per active output (temporarily two during replacement).
An “all outputs” action targets currently connected displays. The plugin does not
stop other wallpaper programs: disable a competing video-wallpaper plugin before
using this one on the same output. Image selections use Noctalia's native wallpaper
API. Video playback preserves the existing static image for restoration.

## Load the development plugin

Build the renderer first, then register this repository as a local path source:

```sh
noctalia msg plugins source add vwallpaper-dev path "$PWD"
noctalia msg plugins enable maru/vwallpaper
noctalia msg settings-open-plugin maru/vwallpaper
noctalia msg panel-toggle maru/vwallpaper:picker
```

Choose your media directory in plugin settings (default `~/Videos`). Add
`maru/vwallpaper:wallpaper` through Noctalia's bar widget settings to place the icon.
The **Panel button icon** setting changes the bar icon. Its default is Noctalia’s
[`wallpaper-selector`](https://github.com/noctalia-dev/noctalia/blob/main/src/shell/bar/widgets/wallpaper_widget.h)
glyph, matching the built-in wallpaper picker.
Choose one output in the picker to expose its scale and policy overrides after
assigning a video; quality overrides appear when optimized copies are enabled.
The folder scan currently covers that directory only, up to 4096 supported files.
It runs on open/rescan; there is no recursive scan or directory watcher yet.

For a one-time directory override without changing settings:

```sh
noctalia msg panel-open maru/vwallpaper:picker /absolute/path/to/media
```

To stop the plugin and remove the development registration:

```sh
noctalia msg plugins disable maru/vwallpaper
noctalia msg plugins source remove vwallpaper-dev
```

Assignments remain in Noctalia's plugin data directory across disable/enable. Use
Restore in the picker to remove assignments. Re-enabling resumes saved assignments
and preserves manual pause. Current display identity is the connector name; stable
monitor hardware identity is not implemented yet.

`cmake --install build --prefix /your/prefix` stages the renderer and plugin under
`bin` and `share/noctalia/plugins/vwallpaper`. An installed build requires the system
LayerShellQt runtime; the workspace-local dependency below is for development.

## Build

Build dependencies: CMake 3.21+, C/C++17 compilers, Qt 6.8+
Core/Gui/Quick/Multimedia/DBus, LayerShellQt 6.6+ and its Wayland shell integration
plugin, pkg-config, wayland-client, and wayland-scanner.
Runtime requires Python 3.11+, FFmpeg/ffprobe (libx264 for optimized copies),
and both built helpers. Power/session monitoring uses UPower and systemd-logind.

With dependencies installed:

```sh
cmake -S . -B build -G Ninja
cmake --build build
ctest --test-dir build --output-on-failure
```

For this development workspace, LayerShellQt 6.7.5 was extracted from the
distribution package into `.deps/layer-shell-qt` without system installation.
It is an ignored local build dependency, not vendored source. Reconfigure with:

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH="$PWD/.deps/layer-shell-qt/usr"
cmake --build build
export QT_PLUGIN_PATH="$PWD/.deps/layer-shell-qt/usr/lib/qt6/plugins"
```

## Run the proof

```sh
build/vwallpaper-renderer --list-outputs
build/vwallpaper-renderer --output eDP-1 --file /absolute/path/video.mp4 --fit fill
```

Use `--preview` instead of `--output` to open an ordinary development window.
An existing wallpaper surface may cover the standalone background proof. The native
service coordinates Noctalia's static surface when you use the plugin picker.

Keep stdin open. After the `ready` event, send one JSON object per line:

```json
{"version":1,"command":"pause","reason":"manual"}
{"version":1,"command":"pause","reason":"fullscreen"}
{"version":1,"command":"resume","reason":"fullscreen"}
{"version":1,"command":"status"}
{"version":1,"command":"resume","reason":"manual"}
{"version":1,"command":"quit"}
```

Allowed reasons are `manual`, `fullscreen`, `battery`, `low_battery`, `lock`,
`suspend`, and `output_off`. These are explicit inputs in the prototype;
automatic event detection is not wired up yet. Commands before readiness are
rejected. Playback resumes only when the reason set is empty.

Events are `ready`, `status`, `error`, `output_removed`, and `stopped`, each with
`version: 1`. Status includes playback position, delivered frame count, and
active pause reasons. Stdout carries protocol messages; stderr carries diagnostics.
The controller must drain both streams. EOF exits cleanly. `vwallpaper/controller.py`
provides the socket adapter for Noctalia, watches readiness/failure events, and
closes renderer stdin during shutdown. A missing controller heartbeat restores
Noctalia's static surface within 15 seconds. The controller exits after its output
reader disappears; normal plugin teardown terminates it directly.

## Verification

```sh
ctest --test-dir build --output-on-failure
# Temporarily displays a synthetic video on the selected Niri output:
python3 tests/wayland_smoke.py eDP-1
python3 tests/controller_wayland.py
# Opens and fullscreens an owned preview, then restores focus:
python3 tests/policy_wayland.py
noctalia plugins lint vwallpaper
```

The headless test exercises actual H.264 decoding, loop boundaries, overlapping
pause reasons, resume, malformed/unsupported commands, invalid paths/output/scale,
corrupt media, filenames containing spaces and shell-special characters, and
parent EOF cleanup.

The live test checks Niri's layer list for a background surface with no keyboard
focus, verifies pause/resume through frame counts, samples paused process CPU,
and checks surface removal after exit. It leaves the desktop configuration intact.

The controller suite covers failed replacement rollback, independent per-output
pause, persistence, reconnect, scale overrides, renderer crashes, failed state writes,
private socket access, and shutdown. The Lua service test covers static-surface
handoff, scoped restore, stale snapshots, heartbeat failure, and teardown. Unix
socket tests must run in an environment that permits local sockets.

Native integration was also checked on Noctalia 5.1.0: the plugin loaded, its private
controller accepted commands, and the picker displayed generated image/video
thumbnails. A separate live controller test used the real Qt renderer to check
startup, pause, failed-video rollback, scale replacement, and cleanup. The temporary
source and enabled plugin were removed after testing; the existing Gslapper wallpaper
was left running. The bar entry is implemented and syntax-checked but has not yet
been placed on the live bar. Full physical multi-monitor validation is still pending.

Observed on the local Noctalia 5.1.0 / Niri 26.04 / Qt 6.11.2 session:

- Output: `eDP-1`, 1920×1080 physical pixels, 1.2 scale, 165 Hz.
- Test clip: H.264, 640×360, 30 FPS, one-second loop.
- 38 delivered frames after the initial 1.2-second playback sample.
- Zero delivered frames and zero process CPU ticks during a one-second settled pause.
- Resume and layer cleanup passed.

This is a short functional sample, not a low-end performance certification.
Hardware decoder selection, GPU power, multi-output behavior, visual loop quality,
and extended stability still need measurement. Frame delivery and a successful
surface commit do not by themselves prove that every displayed frame is artifact-free.

## Power and fullscreen behavior

Defaults pause at 20% battery or below, on session lock/inactivity, on suspend,
and behind a detected fullscreen window. Pausing whenever unplugged is optional.
Setting the low-battery threshold to zero disables that threshold. Manual pause
persists independently; clearing an automatic reason never clears manual pause.
A paused startup decodes one still frame before exposing its surface.

The `vwallpaper-monitor` helper subscribes to UPower, logind, and Wayland
foreign-toplevel events; the controller subscribes to Niri's event stream.
Unavailable sensors disable their automatic reason. Lock support depends on the
locker reporting logind state. Physical lock/suspend and unplug/replug tests remain
pending; automatic DPMS/output-off detection is not implemented.

The tested Niri IPC does not expose an explicit fullscreen flag. Compatibility
mode combines the foreign-toplevel fullscreen flag with a unique application/title
match, the selected window on each output's active workspace, and full-output tile
bounds. Ambiguous duplicate windows are skipped. Overview and hidden workspaces
are excluded. Fixed-size fullscreen backdrops are handled by tile bounds. A
windowed-fullscreen tile that covers the entire output is indistinguishable under
this fallback. Geometry alone never triggers pause.

The live test passed on Niri 26.04: true fullscreen paused, exiting preserved manual
pause, manual resume worked, and ordinary windowed fullscreen did not pause.
The reducer tests also cover separate outputs/workspaces, duplicate matches,
fixed-size clients, overview, disconnection, and overlapping power reasons.

## Effective playback quality

Enable **optimized playback copies** in settings to apply FPS/resolution caps.
Defaults are 30 FPS and a 1920×1080 bounding box; source/15/24/30/60 FPS and
source/720p/1080p/1440p/2160p bounds are available, with per-output overrides.
Aspect ratio and normal playback speed are preserved by default; smaller/slower
sources are not upscaled or given additional frames. Originals remain untouched.

**Slow motion when reducing FPS** is off by default. With optimized copies enabled,
turn it on to retain each source frame at the selected lower FPS: 60 → 30 FPS
plays at half speed and doubles the loop duration. Source FPS or a cap at/above
the source rate leaves speed unchanged. This changes motion speed; it does not
interpolate new frames or increase display smoothness. Variable-rate frames are
retimed to a regular cadence. The option applies to per-output FPS overrides too,
and creates a separate cached copy so toggling it cannot reuse the wrong speed.

FFmpeg generates muted H.264 copies using one encode/filter thread and one job at a
time. This reduces the video actually decoded, rather than only reducing display
size. Preparation can be expensive; by default it waits for confirmed AC power.
Existing cached copies work on battery. Loss of AC during conversion cancels that
job with a retry message. The picker shows progress and cancellation; the previous
wallpaper keeps playing until a replacement is ready.

The default cache budget is 2048 MiB. Unused copies are pruned before new work;
active copies are protected. Low disk space, incomplete encodes, modified sources,
and unsupported HDR conversion fail without replacing the current wallpaper.
Use both Source quality settings or disable optimized copies for HDR originals;
HDR display correctness has not been validated. Cancelling preserves the prior
assignment. A live optimized-copy playback test passed, and automated FFmpeg
checks verify dimensions, frame rate, duration, cache reuse, and original-file hash.

## Remaining release work

1. Measure hardware decoding, GPU/battery use, long-run stability, and visual
   transitions on the intended low-end machine.
2. Validate physical multi-monitor, lock/suspend, and battery transitions; implement
   DPMS/output-off monitoring.
3. Validate the placed bar widget and full UI-driven wallpaper handoff with this
   plugin as the sole wallpaper owner.
4. Add stable monitor identity, directory watching, remaining placement controls,
   keyboard/UI polish, and translation coverage.
