local helper = noctalia.pluginDir() .. "/controller.py"
local stateDir = noctalia.pluginDataDir()
local hidden = {}
local clearing = {}
local online = false
local lastSeen = 0
local exiting = false
local startedAt = noctalia.nowMs()
noctalia.setUpdateInterval(1000)

local function quote(value)
    return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function restore()
    for output in pairs(hidden) do noctalia.setWallpaperEnabled(output, true) end
    hidden = {}
end

local function report(message)
    noctalia.state.set("serviceError", message)
    noctalia.log("Mallowpaper: " .. message)
end

local function send(data)
    if not online or exiting then return end
    local accepted = noctalia.runAsync({"python3", helper, "send", "--state-dir", stateDir,
        noctalia.json.encode(data)}, function(result)
        if result.exitCode ~= 0 then
            report("Controller command failed: " .. (result.stdout or result.stderr or "unknown error"))
        end
    end)
    if not accepted then report("Could not queue controller command") end
end

local function sync()
    local outputs = {}
    for _, output in ipairs(noctalia.outputs()) do table.insert(outputs, output.name) end
    send({action = "sync", outputs = outputs, fit = noctalia.getConfig("fit"), settings = {
        pause_battery = noctalia.getConfig("pause_battery"), low_battery = noctalia.getConfig("low_battery"),
        pause_lock = noctalia.getConfig("pause_lock"), pause_suspend = noctalia.getConfig("pause_suspend"),
        pause_fullscreen = noctalia.getConfig("pause_fullscreen"), fullscreen_focused = noctalia.getConfig("fullscreen_focused"),
        slow_fps = noctalia.getConfig("slow_fps"), optimize = noctalia.getConfig("optimize"), fps = tonumber(noctalia.getConfig("fps")),
        height = tonumber(noctalia.getConfig("height")), ac_only = noctalia.getConfig("ac_only"),
        cache_mb = noctalia.getConfig("cache_mb")}})
end

local function receive(line)
    if exiting then return end
    local data = noctalia.json.decode(line)
    if type(data) ~= "table" or data.version ~= 1 then return end
    lastSeen = noctalia.nowMs()
    if data.event == "online" then
        online = true
        noctalia.state.set("online", true)
        noctalia.state.set("serviceError", "")
        sync()
    elseif data.event == "state" then
        local active = data.active or {}
        for _, output in ipairs(noctalia.outputs()) do
            local name = output.name
            if active[name] and not clearing[name] then
                if not hidden[name] then noctalia.setWallpaperEnabled(name, false) end
                hidden[name] = true
            else
                if hidden[name] then noctalia.setWallpaperEnabled(name, true) end
                hidden[name] = nil
                if not active[name] then clearing[name] = nil end
            end
        end
        noctalia.state.set("playback", data)
    elseif data.event == "offline" then
        online = false
        noctalia.state.set("online", false)
        restore()
    elseif data.event == "error" then
        report(data.message or "Playback command failed")
    end
end

local function handle(data)
    if type(data) ~= "table" then return end
    if not online then report("Playback service is unavailable; check the renderer setting and re-enable the plugin") return end
    noctalia.state.set("serviceError", "")
    if data.action == "clear" or data.action == "image" then
        local playback = noctalia.state.get("playback") or {}
        local profiles = playback.profiles or {}
        for _, output in ipairs(noctalia.outputs()) do
            if (data.output == "*" or data.output == output.name)
                and (profiles[output.name] or hidden[output.name] or data.action == "image") then
                clearing[output.name] = true
                noctalia.setWallpaperEnabled(output.name, true)
                hidden[output.name] = nil
                if data.action == "image" and type(data.path) == "string" then
                    noctalia.setWallpaper(output.name, data.path)
                end
            end
        end
        send({action = "clear", output = data.output, request = data.request})
    else
        send(data)
    end
end

noctalia.state.watch("command", handle)
function onIpc(event, payload)
    if event == "command" then handle(noctalia.json.decode(payload or "")) end
end
function onOutputsChanged() sync() end
-- No onConfigChanged: let Noctalia restart the service with the new executable/settings.
function update()
    if not online and lastSeen == 0 and noctalia.nowMs() - startedAt > 10000 then
        lastSeen = noctalia.nowMs()
        report("Playback controller did not start; check the renderer setting and re-enable the plugin")
    end
    if online and noctalia.nowMs() - lastSeen > 15000 then
        online = false
        noctalia.state.set("online", false)
        restore()
        report("Playback controller stopped responding; static wallpaper restored")
    end
end
function onExit()
    -- The host terminates this runtime's runStream process. A delayed socket shutdown
    -- could instead reach a new controller during hot reload, so do not send one here.
    exiting = true
    noctalia.state.set("online", false)
    restore()
end

local renderer = noctalia.getConfig("renderer_path")
if renderer == "" then
    renderer = noctalia.pluginDir() .. "/bin/mallowpaper-renderer"
    if not noctalia.fileExists(renderer) then renderer = noctalia.pluginDir() .. "/../build/mallowpaper-renderer" end
end
renderer = noctalia.expandPath(renderer)
noctalia.state.set("online", false)
if not stateDir or not noctalia.fileExists(renderer) then
    report("Build the renderer or select its executable in plugin settings")
else
    local environment = ""
    local localPlugins = noctalia.pluginDir() .. "/../.deps/layer-shell-qt/usr/lib/qt6/plugins"
    if noctalia.fileExists(localPlugins) then environment = "QT_PLUGIN_PATH=" .. quote(localPlugins) .. " " end
    local command = "exec env " .. environment .. "python3 -u " .. quote(helper)
        .. " serve --state-dir " .. quote(stateDir) .. " --renderer " .. quote(renderer)
    if not noctalia.runStream(command, receive) then report("Could not start playback controller") end
end
