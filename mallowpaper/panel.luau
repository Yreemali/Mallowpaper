local common = require("./common.luau")
local items, thumbs, pending = {}, {}, {}
local selected, query, filter = "*", "", "all"
local page, generation = 1, 0
local opened, scanning, thumbBusy = false, false, false
local errorMessage = ""
local directoryOverride = nil
local PAGE_SIZE = 12
local render, load, nextThumbnail
local function playback() return noctalia.state.get("playback") or {} end
local function matches()
    local found = {}
    for _, item in ipairs(items) do
        if (filter == "all" or item.kind == filter) and string.find(string.lower(item.name), query, 1, true) then
            table.insert(found, item)
        end
    end
    return found
end
local function act(action, fields)
    fields = fields or {}
    fields.output = selected
    common.command(action, fields)
end

nextThumbnail = function()
    if not opened or thumbBusy then return end
    local visible = matches()
    for i = (page - 1) * PAGE_SIZE + 1, math.min(page * PAGE_SIZE, #visible) do
        local item = visible[i]
        if not thumbs[item.path] and not pending[item.path] then
            pending[item.path] = true
            thumbBusy = true
            local cache = noctalia.pluginDataDir() .. "/thumbnails"
            local accepted = noctalia.runAsync({"python3", common.helper(), "thumbnail", item.path, cache}, function(result)
                thumbBusy = false
                if result.exitCode == 0 then
                    local data = noctalia.json.decode(result.stdout)
                    if data then thumbs[item.path] = data.path end
                end
                if opened then render() nextThumbnail() end
            end)
            if not accepted then thumbBusy = false end
            return
        end
    end
end

load = function()
    generation = generation + 1
    local token = generation
    scanning = true
    errorMessage = ""
    local directory = noctalia.expandPath(directoryOverride or noctalia.getConfig("directory"))
    local accepted = noctalia.runAsync({"python3", common.helper(), "scan", directory}, function(result)
        if token ~= generation then return end
        scanning = false
        if result.exitCode == 0 then
            local data = noctalia.json.decode(result.stdout)
            items = data and data.items or {}
            if data and data.limited then errorMessage = "Showing the first 4096 media files" end
        else
            items = {}
            errorMessage = "Could not scan wallpaper directory. Check plugin settings."
        end
        page = 1
        if opened then render() nextThumbnail() end
    end)
    if not accepted then scanning = false errorMessage = "Could not start directory scan" end
    render()
end

render = function()
    if not opened then return end
    local state = playback()
    local active, profiles = state.active or {}, state.profiles or {}
    local outputs = noctalia.outputs()
    local names, labels, index = {"*"}, {"All outputs"}, 0
    local videos, paused = 0, 0
    for _, output in ipairs(outputs) do
        table.insert(names, output.name)
        table.insert(labels, output.name)
        if output.name == selected then index = #names - 1 end
        if (selected == "*" or selected == output.name) and active[output.name] then
            videos = videos + 1
            if active[output.name].manual_paused then paused = paused + 1 end
        end
    end
    if index == 0 then selected = "*" end
    local visible = matches()
    local pages = math.max(1, math.ceil(#visible / PAGE_SIZE))
    page = math.min(page, pages)
    local rows, row = {}, {}
    for i = (page - 1) * PAGE_SIZE + 1, math.min(page * PAGE_SIZE, #visible) do
        local item = visible[i]
        local assigned = false
        for name, current in pairs(active) do
            if (selected == "*" or name == selected) and current.path == item.path then assigned = true end
        end
        local apply = function() act(item.kind == "video" and "set" or "image", {path = item.path}) end
        local preview
        if thumbs[item.path] then
            preview = ui.image({path = thumbs[item.path], width = 220, height = 124, fit = "cover", radius = 8,
                border = assigned and "primary" or "outline", borderWidth = assigned and 3 or 1, onClick = apply})
        else
            preview = ui.box({width = 220, height = 124, fill = "surface_variant", radius = 8, onClick = apply})
        end
        table.insert(row, ui.column({key = item.path, gap = 4, width = 220}, {
            preview, ui.label({text = string.upper(item.kind) .. " · " .. item.name,
                fontSize = 11, maxLines = 1, maxWidth = 220, color = "on_surface_variant"})}))
        if #row == 4 or i == math.min(page * PAGE_SIZE, #visible) then
            table.insert(rows, ui.row({gap = 12}, row))
            row = {}
        end
    end
    if #visible == 0 then table.insert(rows, ui.label({text = scanning and "Scanning wallpapers…" or "No matching wallpapers"})) end
    local tabs = {}
    for _, tab in ipairs({{"all", "All"}, {"image", "Images"}, {"video", "Videos"}}) do
        table.insert(tabs, ui.button({text = tab[2], selected = filter == tab[1], onClick = function()
            filter = tab[1] page = 1 render() nextThumbnail()
        end}))
    end
    local children = {
        ui.row({gap = 12, align = "center"}, {
            ui.label({text = "Wallpaper", fontSize = 20, fontWeight = "bold", flexGrow = 1}),
            ui.button({glyph = "refresh", tooltip = "Rescan directory", onClick = function() thumbs = {} pending = {} load() end}),
            ui.button({glyph = "settings", tooltip = "Settings", onClick = function() noctalia.openSettings() end}),
            ui.button({glyph = "close", tooltip = "Close", onClick = function() panel.close() end})}),
        ui.row({gap = 12}, {
            ui.input({key = "search", placeholder = "Search wallpapers", flexGrow = 1, onChange = function(value)
                query = string.lower(value) page = 1 render() nextThumbnail()
            end}),
            ui.select({key = "outputs", width = 200, options = labels, selectedIndex = index, onChange = function(value)
                selected = names[(tonumber(value) or 0) + 1] or "*" render()
            end})}),
        ui.row({gap = 8}, tabs),
        ui.row({gap = 12, padding = 12, fill = "surface_variant", radius = 10, align = "center"}, {
            ui.label({text = tostring(#outputs) .. " outputs · " .. tostring(videos) .. " videos", flexGrow = 1}),
            ui.button({text = paused > 0 and "Resume videos" or "Pause videos", enabled = videos > 0,
                onClick = function() act("pause", {paused = paused == 0}) end}),
            ui.button({text = selected == "*" and "Restore all" or "Restore", onClick = function() act("clear") end})})
    }
    if selected ~= "*" and profiles[selected] then
        local fitOptions, fitValues = {"Default scale", "Fill / crop", "Fit", "Stretch"}, {"inherit", "fill", "fit", "stretch"}
        local fitIndex = 0
        for i, value in ipairs(fitValues) do if profiles[selected].fit == value then fitIndex = i - 1 end end
        table.insert(children, ui.select({key = "scale-" .. selected, options = fitOptions, selectedIndex = fitIndex,
            onChange = function(value) act("fit", {fit = fitValues[(tonumber(value) or 0) + 1]}) end}))
        local function override(key, options, values, action)
            local current = profiles[selected][key]
            local chosen = 0
            for i, value in ipairs(values) do if current == value then chosen = i - 1 end end
            return ui.select({key = key .. "-" .. selected, options = options, selectedIndex = chosen, flexGrow = 1,
                onChange = function(index)
                    act(action, {values = {[key] = values[(tonumber(index) or 0) + 1]}})
                end})
        end
        if noctalia.getConfig("optimize") then
            table.insert(children, ui.row({gap = 12}, {
                override("fps", {"Default FPS", "Source FPS", "15 FPS", "24 FPS", "30 FPS", "60 FPS"},
                    {"inherit", 0, 15, 24, 30, 60}, "quality"),
                override("height", {"Default resolution", "Source resolution", "1280 × 720", "1920 × 1080", "2560 × 1440", "3840 × 2160"},
                    {"inherit", 0, 720, 1080, 1440, 2160}, "quality")}))
        end
        table.insert(children, ui.row({gap = 12}, {
            override("pause_battery", {"Battery: default", "Battery: pause", "Battery: keep playing"}, {"inherit", true, false}, "policy"),
            override("pause_fullscreen", {"Fullscreen: default", "Fullscreen: pause", "Fullscreen: keep playing"}, {"inherit", true, false}, "policy")}))
    end
    local reasonLabels = {manual = "manually paused", battery = "on battery", low_battery = "low battery",
        lock = "session locked/inactive", suspend = "suspended", fullscreen = "fullscreen window"}
    for output, current in pairs(active) do
        if selected == "*" or selected == output then
            local reasons = {}
            for _, reason in ipairs(current.pause_reasons or {}) do table.insert(reasons, reasonLabels[reason] or reason) end
            if #reasons > 0 then table.insert(children, ui.label({text = output .. ": " .. table.concat(reasons, ", "), fontSize = 12})) end
        end
    end
    for output, progress in pairs(state.preparation or {}) do
        if selected == "*" or selected == output then
            local label = progress.stage == "waiting_for_ac" and "Waiting for AC power"
                or progress.stage == "queued" and "Queued for preparation"
                or "Preparing playback copy: " .. tostring(progress.percent) .. "%"
            table.insert(children, ui.row({gap = 8}, {
                ui.label({text = output .. ": " .. label, flexGrow = 1}),
                ui.button({text = "Cancel", onClick = function() common.command("cancel", {output = output}) end})}))
        end
    end
    local message = noctalia.state.get("serviceError") or ""
    if message == "" then message = errorMessage end
    for output, problem in pairs(state.errors or {}) do
        if selected == "*" or output == selected then message = output .. ": " .. problem break end
    end
    if message ~= "" then table.insert(children, ui.label({text = message, color = "error", maxLines = 2})) end
    table.insert(children, ui.scroll({flexGrow = 1}, {ui.column({gap = 12}, rows)}))
    table.insert(children, ui.row({gap = 12, align = "center"}, {
        ui.label({text = tostring(#visible) .. " items", flexGrow = 1, color = "on_surface_variant"}),
        ui.button({glyph = "chevron-left", enabled = page > 1, onClick = function() page = page - 1 render() nextThumbnail() end}),
        ui.label({text = tostring(page) .. " / " .. tostring(pages)}),
        ui.button({glyph = "chevron-right", enabled = page < pages, onClick = function() page = page + 1 render() nextThumbnail() end})}))
    panel.render(ui.column({padding = 16, gap = 12, flexGrow = 1}, children))
end

function onOpen(context)
    opened = true
    directoryOverride = type(context) == "string" and context ~= "" and context or nil
    load()
end
function onClose() opened = false generation = generation + 1 end
noctalia.state.watch("playback", function() render() end)
noctalia.state.watch("serviceError", function() render() end)
