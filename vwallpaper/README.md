# Mallowpaper

Video wallpapers for Noctalia, built for Niri with Qt Multimedia and FFmpeg.
Choose images and videos from a native picker, set a different wallpaper on each
display, and pause playback from your bar.

## Features

- Searchable wallpaper library with thumbnails, image/video filters, and output selection.
- Per-display fill/crop, fit, stretch, quality, and pause-policy overrides.
- Automatic pausing for detected fullscreen windows, battery conditions, and
  supported lock/suspend events. Manual pause remains independent.
- Optional cached FPS/resolution limits that reduce decoding work and preserve originals.
- Optional slow motion when lowering FPS: 60 → 30 FPS plays at half speed, keeping
  every source frame. Off by default.
- AC-only preparation by default, progress, cancellation, and a bounded playback cache.
- Saved assignments, static-wallpaper restoration, and a customizable bar icon.

## Plugin

| Field | Value |
| --- | --- |
| ID | `maru/vwallpaper` |
| Author | Maru |
| Entries | Bar widget: `wallpaper`; panel: `picker`; service: `service` |
| Compatibility | Noctalia 5.1.x, plugin API 25; tested on Niri 26.04 |
| Playback | Qt Multimedia; silent looping video |

## Requirements

Python 3.11+, FFmpeg/ffprobe, Qt 6.8+ with Multimedia and DBus, LayerShellQt 6.6+
and its Wayland integration, plus the built `vwallpaper-renderer` and
`vwallpaper-monitor` helpers. Optimized copies require FFmpeg’s libx264 encoder.
UPower and systemd-logind provide power/session monitoring.

This plugin currently requires a source build; adding the plugin source alone does
not compile its helpers. See the repository’s installation instructions before enabling it.

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

1. Disable competing video-wallpaper plugins on your target displays.
2. Choose **Wallpaper directory** in the plugin settings (default `~/Videos`).
3. Add **Mallowpaper** to your Noctalia bar, then click its icon.
4. Select **All outputs** or a display and choose an image or video.
5. Use pause/resume for playback control and **Restore** to clear video assignments.

Open the picker directly:

```sh
noctalia msg panel-toggle maru/vwallpaper:picker
```

Middle-click the bar icon to toggle manual pause on its display; right-click for
settings. **Panel button icon** changes the glyph, defaulting to Noctalia’s standard
`wallpaper-selector` icon.

Enable **Prepare lower-cost playback copies** to expose FPS, resolution, and
slow-motion controls. Defaults are 30 FPS, 1080p bounds, AC-only preparation,
and a 2048 MiB cache. Select one display in the picker for overrides.

## Development disclosure

Created by **Maru** with AI assistance in implementation and documentation.
AI-assisted code can contain mistakes, and this project may still have bugs,
compatibility problems, or performance issues despite testing. Please report
problems with your Noctalia/Niri versions, relevant logs, and steps to reproduce.

## Notes

This is a development release. Fullscreen matching is conservative and may skip
ambiguous windows. Lock detection depends on logind reporting; automatic
DPMS/output-off detection and HDR optimization are not implemented. Physical
multi-monitor, power-transition, and low-end performance validation remain in progress.
