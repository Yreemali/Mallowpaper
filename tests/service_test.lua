local values, watched, surfaces, commands = {}, {}, {}, {}
local receive
local now = 0
noctalia = {
    pluginDir = function() return "/plugin" end,
    pluginDataDir = function() return "/state" end,
    nowMs = function() return now end,
    setUpdateInterval = function() end,
    getConfig = function(key) return key == "fit" and "fill" or "" end,
    expandPath = function(path) return path end,
    fileExists = function() return true end,
    outputs = function() return {{name = "eDP-1"}, {name = "DP-1"}} end,
    setWallpaperEnabled = function(output, enabled) surfaces[output] = enabled end,
    setWallpaper = function() end,
    log = function() end,
    state = {
        set = function(key, value) values[key] = value end,
        get = function(key) return values[key] end,
        watch = function(key, fn) watched[key] = fn end,
    },
    json = {encode = function(value) return value end, decode = function(value) return value end},
    runAsync = function(argv) table.insert(commands, argv) return true end,
    runStream = function(_, fn) receive = fn return true end,
}
dofile(arg[1])
assert(next(surfaces) == nil, "Startup must not take ownership of unrelated surfaces")
receive({version = 1, event = "online"})
receive({version = 1, event = "state", active = {}, profiles = {}})
watched.command({action = "clear", output = "*"})
assert(next(surfaces) == nil, "Restore on an unassigned output must leave it alone")
local playing = {version = 1, event = "state", active = {["eDP-1"] = {path = "/clip.mp4"}},
    profiles = {["eDP-1"] = {path = "/clip.mp4"}}}
receive(playing)
assert(surfaces["eDP-1"] == false and surfaces["DP-1"] == nil)
watched.command({action = "clear", output = "eDP-1"})
assert(surfaces["eDP-1"] == true, "Restore must reveal static before stopping playback")
receive(playing)
assert(surfaces["eDP-1"] == true, "A queued old snapshot must not hide restored wallpaper")
receive({version = 1, event = "state", active = {}, profiles = {}})
receive(playing)
assert(surfaces["eDP-1"] == false)
now = 16000
update()
assert(surfaces["eDP-1"] == true, "Lost heartbeat must restore static wallpaper")
receive({version = 1, event = "online"})
receive(playing)
onExit()
assert(surfaces["eDP-1"] == true)
assert(surfaces["DP-1"] == nil)
print("PASS: readiness handoff, scoped restore, stale snapshots, watchdog, teardown")
