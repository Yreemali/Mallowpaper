![Status](https://img.shields.io/badge/status-release%20preparation-yellow)
![Language](https://img.shields.io/badge/language-C%2B%2B17%20%2B%20Python%20%2B%20Luau-blue)
![Playback](https://img.shields.io/badge/playback-Qt%20Multimedia%20%2B%20FFmpeg-purple)
![Desktop](https://img.shields.io/badge/desktop-Noctalia%20%2B%20Niri-green)
![License](https://img.shields.io/badge/license-MIT-blue)
![Development](https://img.shields.io/badge/development-AI--assisted-orange)

# Mallowpaper

A video wallpaper plugin for Noctalia and Niri, using Qt Multimedia for playback
and FFmpeg for media processing. It provides a native wallpaper picker,
per-display assignments, automatic pause policies, and optional FPS/resolution
limits through cached playback copies.

Targets **Noctalia 5.1.x with plugin API 25**. The tested environment is
Noctalia 5.1.0, Niri 26.04, and Qt 6.11.2. Installation currently requires building
the native helpers from source.

## Overview

The native **Wallpaper** picker handles media selection and output targeting.
Static images use Noctalia’s renderer; videos use a dedicated Qt background surface
on each assigned output. The bar widget provides picker access and playback controls.

```text
Local images and videos
          ↓
Noctalia Wallpaper picker
          ↓
Per-display assignments
   ┌──────┴────────┐
   ↓               ↓
Static images   Qt video playback
                   ↑
          Pause and quality controls
```

Qt Multimedia decodes and presents video. FFmpeg generates still thumbnails and
optional lower-resolution or lower-FPS copies. Niri events, Wayland toplevel state,
and power/session signals determine automatic pause reasons.

## Features

- **One wallpaper picker:** searchable image/video library, still thumbnails,
  filters, pagination, and a configurable media directory.
- **Per-display controls:** assign videos to one or all connected displays, with
  individual fill/crop, fit, stretch, quality, and pause-policy overrides.
- **Bar integration:** customizable icon, click to choose a wallpaper, middle-click
  to pause/resume, and right-click for settings.
- **Automatic pausing:** fullscreen detection on each display’s active Niri
  workspace, battery and low-battery rules, and logind lock/suspend monitoring.
  Manual pause stays active until you clear it.
- **Effective quality limits:** optional cached playback copies reduce the video
  actually decoded. Choose source, 15, 24, 30, or 60 FPS and resolution bounds from
  720p to 2160p. Originals remain unchanged.
- **Optional slow motion:** retain source frames when lowering FPS. For example,
  60 → 30 FPS plays at half speed. Disabled by default.
- **Controlled preparation:** one FFmpeg job at a time, AC-only preparation by
  default, a bounded cache, progress reporting, and cancellation.
- **Persistent playback:** saved assignments and manual pause survive restarts.
  Failed replacements keep the current video; Restore returns to the static wallpaper.

## Architecture

| Component | Implementation | Responsibility |
| --- | --- | --- |
| Noctalia integration | Luau | Picker, bar widget, settings, and static-surface handoff |
| Playback controller | Python / asyncio | Private Unix socket, renderer lifecycle, persisted profiles, and pause policies |
| Video renderer | C++17 / Qt Quick / Qt Multimedia | One layer-shell background surface and silent looping player per active output |
| Environment monitor | C++17 / Qt DBus / Wayland client | UPower, logind, and foreign-toplevel state |
| Media preparation | FFmpeg / ffprobe | Cached thumbnails, metadata, and optional playback copies |

The service starts the controller, which owns renderer processes and the shared
environment monitor. The controller also subscribes to Niri’s event stream.
Renderer commands and events use versioned JSON lines over standard input/output.

Replacement playback is confirmed ready before retiring the previous renderer.
During this handoff, an output can temporarily have two renderers. On failure,
the previous video remains active; if an active renderer exits unexpectedly,
the service restores Noctalia’s static wallpaper surface.

Manual, fullscreen, battery, low-battery, lock, and suspend reasons are tracked
independently. Playback resumes only after all active reasons have cleared.
A paused startup decodes an initial frame for presentation.

## Playback preparation

Quality limits are opt-in and apply to cached H.264 copies. Reducing resolution
before playback reduces decoded pixel dimensions; reducing FPS reduces the encoded
frame cadence. Normal mode preserves playback speed. Slow-motion mode assigns each
source frame one output interval, extending duration when the selected FPS is lower.

Preparation uses one FFmpeg job at a time with a single encode/filter thread.
Cache identity includes the source path, size, modification time, quality limits,
and slow-motion mode. Active copies are protected from pruning. Cancellation or a
failed encode preserves the existing assignment. Originals are opened for reading.

## Requirements

| Component | Requirement |
| --- | --- |
| Shell | Noctalia 5.1.x with plugin API 25 |
| Compositor | Niri with Wayland layer-shell and foreign-toplevel support |
| Runtime | Python 3.11+, FFmpeg and ffprobe; libx264 for optimized copies |
| Qt | Qt 6.8+ Core, Gui, Quick, Multimedia, and DBus |
| Layer shell | LayerShellQt 6.6+ and its Wayland shell integration plugin |
| Power monitoring | UPower and systemd-logind |
| Build tools | CMake 3.21+, C/C++17 compilers, Ninja, pkg-config, wayland-client, wayland-scanner |

The build produces `vwallpaper-renderer` and `vwallpaper-monitor`. Other
compositors have not been validated; automatic fullscreen handling is Niri-specific.

## Build and install

Install the dependencies above, then run these commands from the repository root.
Build both native helpers before enabling the plugin; source registration does not
compile or install dependencies:

```sh
cmake -S . -B build -G Ninja
cmake --build build
noctalia msg plugins source add vwallpaper-dev path "$PWD"
noctalia msg plugins enable maru/vwallpaper
```

This registers a local source, so keep the repository and build directory in place.
The plugin discovers the local renderer automatically. For a custom installation,
set **Renderer executable** to its path and keep `vwallpaper-monitor` beside it.

If this workspace already has LayerShellQt extracted under `.deps`, configure with:

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH="$PWD/.deps/layer-shell-qt/usr"
cmake --build build
```

That ignored directory is a local development dependency and is not included in Git.
The service discovers its Qt plugin directory automatically.

## Niri overview setup

To show the video wallpaper in Niri’s overview, add this top-level rule to
`~/.config/niri/config.kdl` (or your active Niri configuration):

```kdl
layer-rule {
    match namespace="^vwallpaper$"
    place-within-backdrop true
}
```

The namespace matches this plugin’s wallpaper surface. Niri’s
[`place-within-backdrop` rule](https://niri-wm.github.io/niri/Configuration%3A-Layer-Rules.html#place-within-backdrop)
places it in the backdrop visible in overview and between workspaces.

## Usage

1. Disable any other video-wallpaper plugin on the displays you want to use.
2. Open **Settings → Plugins → Mallowpaper** and choose your wallpaper directory.
3. Add **Mallowpaper** (`maru/vwallpaper:wallpaper`) in Noctalia’s bar settings.
4. Click its icon, select **All outputs** or a display, and choose an image or video.
5. Select one display to adjust its overrides after assigning a video. Use **Restore**
   to clear its video assignment and reveal the static wallpaper.

You can also open settings or the picker from a terminal:

```sh
noctalia msg settings-open-plugin maru/vwallpaper
noctalia msg panel-toggle maru/vwallpaper:picker
```

Videos loop silently. Image selections use Noctalia’s native wallpaper renderer.
The library scans one directory, up to 4096 files, on open or rescan.
Supported extensions are MP4, MKV, WebM, MOV, M4V, PNG, JPG, JPEG, WebP, and BMP;
video decoding depends on the codecs available to Qt Multimedia.

## Settings

| Setting | Default | Behavior |
| --- | --- | --- |
| Wallpaper directory | `~/Videos` | Folder shown in the picker |
| Panel button icon | `wallpaper-selector` | Change the bar icon with Noctalia’s glyph picker |
| Video scale | Fill | Fill/crop, fit, or stretch; overridable per display |
| Pause on battery | Off | Pause when unplugged; overridable per display |
| Low-battery threshold | 20% | Pause at or below this charge on battery; 0 disables it |
| Pause on lock / suspend | On | Follow available logind session and sleep events |
| Pause on fullscreen | On | Pause behind a detected fullscreen window; overridable per display |
| Focused display only | Off | Restrict fullscreen pausing to the focused display |
| Prepare lower-cost playback copies | Off | Enable effective FPS and resolution limits |
| Maximum playback FPS | 30 | Source, 15, 24, 30, or 60; overridable per display |
| Maximum playback resolution | 1080p | Source or 720p–2160p aspect-preserving bounds; overridable per display |
| Slow motion when reducing FPS | Off | Keep source frames at a lower cadence instead of dropping frames |
| Prepare only on AC | On | Wait for confirmed AC before creating a copy |
| Playback cache | 2048 MiB | Budget for optimized copies; active copies are protected |

Quality controls appear when playback-copy preparation is enabled. Smaller or
slower videos are not upscaled or given extra frames. Slow motion has no effect
with Source FPS or a cap at/above the source rate; it does not interpolate frames.
Preparation can take time. The current wallpaper stays visible until its replacement
is ready, and existing cached copies remain usable on battery.

## Compatibility and limitations

Fullscreen detection combines Niri workspace state with Wayland fullscreen flags
and output coverage. Ambiguous windows with identical application/title pairs are
skipped. A windowed-fullscreen tile covering the entire output cannot be distinguished
from true fullscreen by this fallback.

Lock detection depends on the locker reporting logind state. Automatic DPMS/output-off
detection, stable monitor hardware identities, recursive scanning, and directory
watching are not implemented. HDR copy generation is unsupported; use Source quality
or disable optimized copies. HDR display correctness remains unverified.

Tests cover actual decoding, pause/resume, replacement rollback, effective quality,
slow-motion frame retention, and live Niri fullscreen transitions. Hardware decode,
physical multi-monitor and battery/lock/suspend transitions, long-run resource use,
and visual artifacts still need broader validation.

## Remove

Use **Restore all** in the picker if you want to clear saved assignments, then run:

```sh
noctalia msg plugins disable maru/vwallpaper
noctalia msg plugins source remove vwallpaper-dev
```

Disabling stops playback and restores the static surface. Saved assignments remain
in Noctalia’s plugin data directory unless cleared, and resume when re-enabled.

## Validation

| Area | Current coverage |
| --- | --- |
| Renderer | Actual H.264 decoding, loops, startup pause, resume, IPC errors, and process cleanup |
| Controller | Replacement rollback, persistence, independent output state, cancellation, and crash handling |
| Quality preparation | Encoded FPS/dimensions, duration, slow-motion frame retention, cache reuse, and original preservation |
| Native integration | Picker/settings loading, optimized-copy playback, and Niri fullscreen transitions |
| Pending validation | Physical multi-monitor and power transitions, hardware decoder selection, sustained resource use, and visual artifacts |

Run the automated suites and manifest checks from a built checkout:


```sh
ctest --test-dir build --output-on-failure
noctalia plugins lint vwallpaper
```

See [development and validation](docs/DEVELOPMENT.md) for live tests, helper IPC,
measured behavior, and remaining release work.

## Repository layout

```text
vwallpaper/    Noctalia manifest, Luau entries, Python controller, and plugin page
src/           Qt renderer and environment monitor
qml/           Video presentation surface
protocols/     Wayland protocol definition with upstream license notice
tests/         Automated suites and live Niri checks
docs/          Helper IPC, validation details, and development notes
```

## Reporting issues

[Open an issue](https://github.com/Yreemali/Mallowpaper/issues) with your Noctalia
and Niri versions, relevant logs, video format, and steps to reproduce. If it only
happens on one monitor or on battery, include the affected connector and power state.
For playback problems, include the source FPS/resolution and active quality settings.

## AI-assisted development

Mallowpaper is developed by **Maru** with AI assistance in implementation and
documentation. AI-assisted contributions may contain defects or incorrect
assumptions. Automated checks and targeted live tests cover the scenarios described
here; compatibility, performance, and visual correctness outside that coverage
remain subject to validation.

## License

Mallowpaper is licensed under the [MIT License](LICENSE), copyright © 2026 Maru.
The bundled Wayland protocol retains the copyright and license notice in its
[source file](protocols/wlr-foreign-toplevel-management-unstable-v1.xml).
