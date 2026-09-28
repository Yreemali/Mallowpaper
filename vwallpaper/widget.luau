local common = require("./common.luau")
function update()
    barWidget.setGlyph(noctalia.getConfig("bar_icon") or "wallpaper-selector")
    barWidget.setTooltip("Wallpaper · click to choose, middle click to pause/resume")
end
function onClick() noctalia.togglePanel("maru/vwallpaper:picker") end
function onRightClick() noctalia.openSettings() end
function onMiddleClick()
    local output = barWidget.outputName() or "*"
    local state = noctalia.state.get("playback") or {}
    local current = (state.active or {})[output]
    common.command("pause", {output = output, paused = not (current and current.manual_paused)})
end
update()
