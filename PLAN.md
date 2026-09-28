# Mallowpaper for Noctalia 5.1.x

Status: native service/UI, per-output playback, automatic power/fullscreen policies,
and optional effective FPS/resolution copies are implemented. Five automated test
suites pass. Native picker/settings load, live Niri fullscreen transitions, startup
pause, optimized-copy playback, and replacement rollback have been checked.
See README.md for exact coverage and conservative fullscreen matching limitations.
Hardware-decoder measurement, physical battery/lock/suspend and multi-monitor tests,
DPMS monitoring, low-end performance, and visual artifact validation remain open.

## Target and verified environment

- Noctalia v5.1.0 (5.1.0-1-dirty), Niri 26.04 (8ed0da4), Qt 6.11.2.
- `ffmpeg`, `ffprobe`, and `mpvpaper` are available locally.
- Workspace starts without application code.
- Target Niri first, with Noctalia-native controls and a separately supervised renderer.
- Verify the installed host's plugin API before choosing the manifest's minimum API. Current online documentation includes unreleased APIs; do not assume those exist locally.

## Proposed architecture

1. Noctalia plugin: native Luau service, bar widget, picker panel, and declared settings in `plugin.toml`.
2. Playback helper: C++/Qt 6, Qt Multimedia for playback, Qt Quick for GPU presentation, and a tested Wayland layer-shell integration. One helper initially manages one surface and player per assigned output.
3. FFmpeg/ffprobe: metadata, cached still thumbnails, and optional lower-resolution/lower-FPS playback copies. Original files remain untouched.
4. Event-driven policy controller: Niri workspace/window events, power and session events, manual commands, output lifecycle.
5. Versioned local IPC for commands, ready/error/status events, and graceful shutdown. Use a private runtime socket; validate messages and pass paths as arguments/data, never interpolated shell commands.

Qt Multimedia uses FFmpeg on the target platform in its normal configuration. The first milestone must prove layer-shell integration, hardware decoding, looping, and actual resource savings. If Qt cannot satisfy these gates, replace only the helper backend with direct libavcodec/libavformat and GPU presentation. Do not maintain two production backends initially. FFmpeg CLI alone is not a wallpaper surface renderer.

Noctalia already has an official mpvpaper plugin. Review its integration and lifecycle behavior as a reference; the proposed playback implementation follows the requested Qt/FFmpeg approach.

## Picker and bar widget

Match the supplied screenshot's structure using Noctalia's theme, typography, spacing, and native controls:

- Header with Wallpaper title, settings button, and close button.
- Search and output selector: all connected outputs or one named display.
- All / Images / Videos filters.
- Status strip with output, image, and video counts; pause/resume and restore actions.
- Responsive thumbnail grid with type, filename, current assignment, and useful error states.
- Pagination or bounded visible-item rendering; keyboard navigation, Escape to close, and tooltips.
- Per-output status distinguishes playing, manually paused, fullscreen paused, battery paused, and failed.
- Selecting a file applies it to the selected output scope. “All outputs” affects currently connected outputs; it does not silently overwrite stored profiles for disconnected monitors.
- Restore returns affected outputs to the saved static wallpaper and clears their video assignment.
- Images use Noctalia's wallpaper support; video thumbnails remain still images.

The bar widget uses the same wallpaper icon available in the installed Noctalia version. Left click opens the picker; middle click toggles manual pause for its configured scope; right click exposes settings and restore. Follow host conventions for horizontal/vertical bars, sizing, tooltips, and configurable actions where supported.

## Settings and persistence

Global defaults plus per-display overrides, with an explicit “inherit defaults” option:

| Area | Controls |
| --- | --- |
| Library | Wallpaper directory, optional recursive scan, rescan, thumbnail cache limit |
| Playback | Assigned file, enabled, loop, manual pause; silent playback by default |
| Frame rate | Source, 15, 24, 30, 60 FPS; never increase source FPS automatically |
| Resolution | Source, 720p, 1080p, 1440p, 2160p maximum bounds, custom bounds; preserve aspect ratio |
| Placement | Fill/crop, fit, stretch, center; zoom and crop position; fit background color |
| Decode | Hardware acceleration auto, software compatibility mode, visible backend status |
| Power | Pause on battery, low-battery threshold, battery playback profile, pause on lock/suspend/output-off |
| Fullscreen | Pause on fullscreen for this display; optional focused-display-only policy |
| Cache | Size limit, clear cache, optimization progress/cancel, AC-only conversion by default |

“Resolution” means playback/render resolution, not changing the monitor's display mode. Encode format is a separate advanced concern, not a misleading resolution label.

Persist assignments, overrides, static restore paths, and manual pause state atomically outside the plugin installation directory. Use versioned data with migration. Identify displays by available stable make/model/serial metadata with connector fallback and handle duplicate/missing identifiers explicitly. Retain profiles when monitors disconnect.

## Playback and power rules

- Track pause reasons independently: manual, battery, low battery, fullscreen, lock, suspend, output off.
- Playback resumes only when every applicable pause reason has cleared. Leaving fullscreen must never cancel a manual pause.
- Fullscreen policy is evaluated against the active workspace on each output, not merely the single globally focused workspace. A fullscreen window on a hidden workspace must not pause another visible wallpaper.
- Focused-display-only mode additionally requires that output to be focused. The default pauses any output whose active fullscreen window hides its wallpaper, even when keyboard focus is elsewhere.
- Subscribe to Niri's event stream and rebuild state after reconnect. Handle workspace migration, window closure, output changes, and overview transitions.
- Niri fullscreen detection is an early compatibility gate: the inspected upstream IPC Window model does not expose a simple `is_fullscreen` field. Verify installed protocol capabilities and an explicit fullscreen-state source, such as a supported toplevel protocol with reliable window association. Do not silently equate maximized/window-size matches with fullscreen. Any fallback based on coverage must be labeled and tested as such.
- Pause holds the last valid frame and stops ongoing decoding/presentation work after buffers settle. Deep saving can release decoder resources while retaining a still fallback.
- Resume after suspend/output reconnect rechecks all policy reasons before starting playback.
- Debounce rapid state changes without delaying visible recovery excessively.

## Performance and visual correctness

- Hardware decode when supported and beneficial; bounded queues and software fallback with actionable status.
- Avoid CPU readback of every frame and per-frame image-file pipelines. Keep presentation GPU-based where supported.
- FPS limiting must preserve playback duration and speed. Skipping presentation alone may not lower decode cost.
- Scaling a decoded 4K video to 720p does not remove 4K decoding cost. Offer cached playback copies for genuine low-end savings, keyed by source identity/change metadata and encoding settings.
- Generate optimization copies only through an explicit enable/action; one bounded job at a time, cancellable, normally on AC power. Enforce disk limits and preserve originals.
- Start with a proposed Economy profile of 720p/15 FPS and Balanced profile of 1080p/30 FPS, then tune from measurements. These are defaults to validate, not promised performance levels.
- Cache thumbnails, scan asynchronously, invalidate changed files, and avoid periodic full rescans. Closing the picker stops unnecessary UI work.
- Keep the previous frame or static fallback visible until a replacement's first valid frame is ready. Do not disable Noctalia's static surface before renderer readiness.
- Use Wayland frame pacing, correct buffer lifetimes, aspect handling, color conversion, output scale, and transform handling.
- Validate loop boundaries, switching, and resume for black flashes, corruption, stale frames, and tearing. An intrinsically discontinuous source loop cannot be made seamless just by replaying it.
- Restore static wallpaper on helper failure, plugin disable, or dependency failure. No orphan processes or restart storms; use bounded retry/backoff and ownership tracking.
- Avoid crossfades by default on the economy profile. Shared decoding across displays is a later optimization only if profiling justifies the extra synchronization complexity.

## Delivery milestones

1. **Compatibility and playback proof.** Inspect installed plugin API; build minimal background layer-shell playback; establish reliable fullscreen detection; measure Qt hardware/software paths, pause, loop, and first-frame handoff. Exit: one output works and key API gaps have concrete solutions.
2. **Reliable playback service.** Implement lifecycle, IPC, static restoration, persistent assignment, monitor hotplug, errors, and pause-reason state machine. Exit: repeated enable/disable, crash, and reconnect leave a usable wallpaper and no orphan helper.
3. **Native UI.** Implement screenshot-style picker, directory scanning, still thumbnails, filters/search, bar widget, and native settings. Exit: select image/video and restore on one or all connected outputs through the UI.
4. **Per-display and power behavior.** Add overrides, battery/session events, fullscreen/workspace policy, mixed scaling/rotation, and suspend/resume. Exit: automatic pause affects exactly the intended displays and respects manual pause.
5. **Performance controls.** Implement effective FPS/resolution settings, optional optimized copies, cache limits, and measured profiles. Exit: lower profiles demonstrably reduce cost on the target low-end device.
6. **Release validation and packaging.** Dependency diagnostics, install/uninstall documentation, compatible manifest, translations-ready strings, upgrade migration, and reproducible validation instructions.

## Validation and release criteria

- Automated policy tests cover overlapping pause reasons, per-output active workspaces, focus changes, reconnects, and persisted data migration.
- Integration tests cover IPC validation, missing/deleted/corrupt files, Unicode and shell-special filenames, helper crashes, rapid changes, and bounded cache jobs.
- Manual compositor tests cover one/two displays, different videos, mixed refresh/scale, rotation, disconnect/reconnect, fullscreen on visible/hidden workspaces, overview, lock, suspend, and shell restart.
- Video cases: H.264 and VP9 plus HEVC/AV1 where supported, variable frame rate, portrait media, 720p through 4K, and unsupported/HDR content with explicit handling rather than silent bad colors.
- Compare static wallpaper, playing, paused, and optimization-job workloads. Record CPU, GPU/video decode activity, RSS/VRAM, frame delivery, and battery discharge under controlled conditions.
- Initial acceptance: no observed corrupt/black transition frames in repeated supported cases; paused playback performs no ongoing decode/presentation; memory and queues stabilize during a one-hour run; UI stays responsive during scans; no leaked helper after disable.
- Set numeric CPU/memory/power budgets after measuring the actual low-end target. “Fully optimized” is a measurable release objective, not a hardware-independent guarantee.

## Reference material

- Noctalia runtime API: https://docs.noctalia.dev/noctalia/plugins/development/runtime-api/
- Noctalia API versions: https://docs.noctalia.dev/noctalia/plugins/development/plugin-api/
- Official video wallpaper integration: https://noctalia.dev/plugins/official/mpvpaper
- Niri IPC and event stream: https://github.com/niri-wm/niri/wiki/IPC
- Niri IPC data types: https://github.com/niri-wm/niri/blob/main/niri-ipc/src/lib.rs
- Qt Multimedia backend behavior: https://doc.qt.io/qt-6/qtmultimedia-index.html
- FFmpeg filtering: https://ffmpeg.org/ffmpeg-filters.html
