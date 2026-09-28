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

The plugin combines a local media library, a bar widget, and a supervised renderer.
Each display has an independent assignment and playback state. Fullscreen and power
policies add pause reasons without overriding a persisted manual pause.

- Native **Wallpaper** picker with search, thumbnails, and image/video filters.
- Silent looping video through Qt Multimedia, with per-display scaling.
- Fullscreen and power pause rules that respect manual pause.
- Optional FPS/resolution copies made by FFmpeg; originals stay untouched.
- Optional slow motion: 60 → 30 FPS keeps the frames and plays at half speed.
- Preparation progress, cancellation, AC-only jobs, and a bounded cache.
- A configurable bar icon using Noctalia’s native glyph picker.

## Plugin

| Field | Value |
| --- | --- |
| ID | `maru/vwallpaper` |
| Author | Maru |
| Entries | Bar widget: `wallpaper`; panel: `picker`; service: `service` |
| License | MIT |
| Source | [Yreemali/Mallowpaper](https://github.com/Yreemali/Mallowpaper) |

## Playback architecture

The Luau service supervises a Python controller, which runs one Qt renderer per
active output and a shared environment monitor. A private local socket carries
control requests; renderer commands and events use versioned JSON lines.
Niri workspace events and Wayland fullscreen flags determine output visibility,
while UPower and logind supply power/session state.

FFmpeg preparation is separate from playback. A replacement becomes active only
after its renderer reports readiness. Saved profiles retain the original media
path; cached playback copies are managed independently.

## Requirements

- **Python 3.11+** runs the playback controller and media-library helpers.
- **FFmpeg and ffprobe** create thumbnails, inspect videos, and prepare optional
  playback copies. Copy preparation requires the libx264 encoder.
- **Qt 6.8+** with Core, Gui, Quick, Multimedia, and DBus provides rendering and monitoring.
- **LayerShellQt 6.6+** and its Wayland shell integration place videos behind windows.
- **UPower and systemd-logind** supply battery, session, and sleep events.
- **Niri** supplies workspace/window events and Wayland fullscreen state.
- **`vwallpaper-renderer` and `vwallpaper-monitor`** are built from this repository.
  The service uses `env` to launch its Python controller with the Qt environment.

Build tools: CMake 3.21+, C/C++17 compilers, Ninja, pkg-config, wayland-client,
and wayland-scanner. Other compositors have not been validated.

## Install

Build both native helpers before enabling the plugin. After installing the
requirements, clone the repository and run:

```sh
git clone https://github.com/Yreemali/Mallowpaper.git
cd Mallowpaper
cmake -S . -B build -G Ninja
cmake --build build
noctalia msg plugins source add mallowpaper path "$PWD"
noctalia msg plugins enable maru/vwallpaper
```

Keep this checkout and its build directory in place. The plugin discovers the
helpers in `build/`; registering a Git source by itself does not compile them.
If you already registered this checkout as `vwallpaper-dev`, keep that source
instead of adding a second one.

For a custom helper location, set **Renderer executable** to the absolute path of
`vwallpaper-renderer` and keep `vwallpaper-monitor` beside it. See the
[build documentation](https://github.com/Yreemali/Mallowpaper#build-and-install)
for the workspace-local LayerShellQt setup.

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

1. Disable competing video-wallpaper plugins on the displays you want to use.
2. Open **Settings → Plugins → Mallowpaper** and select your wallpaper directory.
3. In Noctalia’s bar settings, choose **Add Widget → Mallowpaper**.
4. Click the widget to open **Wallpaper**, select **All outputs** or a connector,
   and choose an image or video. Videos loop silently.
5. Select one display to adjust its scale, quality, and pause-policy overrides.
   Use **Restore** to clear the video assignment and reveal the static wallpaper.

| Gesture | Action |
| --- | --- |
| Left click | Open or close the wallpaper picker |
| Middle click | Toggle manual pause for the bar’s display |
| Right click | Open plugin settings |

Noctalia’s configurable gesture bindings can override these defaults.
The icon is configurable and starts with the standard `wallpaper-selector` glyph.

```sh
noctalia msg panel-toggle maru/vwallpaper:picker
noctalia msg settings-open-plugin maru/vwallpaper
```

The picker scans one directory on open or rescan, with a 4096-file limit and
12 items per page. It supports MP4, MKV, WebM, MOV, M4V, PNG, JPG, JPEG, WebP,
and BMP extensions; actual video codec support depends on Qt Multimedia.
Assignments and manual pause survive restarts. **All outputs** affects currently
connected displays; profiles for disconnected displays are retained.

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

- Manual and automatic pause reasons are independent. Leaving fullscreen or
  reconnecting AC cannot clear a manual pause.
- Fullscreen detection checks each output’s active Niri workspace. Ambiguous
  application/title matches are skipped. Windowed fullscreen covering an entire
  output cannot be distinguished from true fullscreen by this fallback.
- Lock handling depends on the locker reporting logind state. Automatic
  DPMS/output-off detection is not implemented.
- Preparation runs one FFmpeg job at a time. It normally waits for AC power,
  exposes progress/cancellation, and keeps the old wallpaper until the new one
  is ready. Losing AC during preparation stops the job with a retry message.
- HDR optimization is unsupported. Use Source FPS and resolution, or disable
  optimized copies. HDR display correctness has not been validated.
- Display profiles use connector names, not monitor serial numbers.
- The plugin writes assignments and cached media in its Noctalia data directory
  and uses a private local control socket. It makes no application-level network
  requests. Playback uses one renderer per display, briefly two during replacement,
  plus a shared controller and environment monitor.
- Physical multi-monitor, battery/lock/suspend transitions, hardware decoding,
  long-run resource use, and visual artifacts need broader validation.

## Validation and feedback

From a built source checkout:

```sh
ctest --test-dir build --output-on-failure
noctalia plugins lint vwallpaper
```

Tests cover decoding, independent pause reasons, failed replacements, persistence,
FPS/resolution conversion, slow-motion frame retention, and cache behavior. Live
Niri fullscreen checks are documented in the
[development guide](https://github.com/Yreemali/Mallowpaper/blob/main/docs/DEVELOPMENT.md).

[Report an issue](https://github.com/Yreemali/Mallowpaper/issues) with your shell and
compositor versions, relevant logs, and steps to reproduce.

## Remove

Use **Restore all** first if you want to clear saved assignments, then:

```sh
noctalia msg plugins disable maru/vwallpaper
noctalia msg plugins source remove mallowpaper
```

Use your existing source name if it differs. Disabling stops the helpers and
restores static wallpaper; saved assignments remain unless cleared.

## AI-assisted development

Mallowpaper is developed by **Maru** with AI assistance in implementation and
documentation. AI-assisted contributions may contain defects or incorrect
assumptions. Automated checks and targeted live tests cover the scenarios described
here; compatibility, performance, and visual correctness outside that coverage
remain subject to validation.

## License

[MIT — Copyright (c) 2026 Maru](https://github.com/Yreemali/Mallowpaper/blob/main/LICENSE).
The bundled Wayland protocol retains its own copyright and license notice.
