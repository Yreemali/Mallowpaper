local common = {}
local nonce = 0
function common.command(action, fields)
    nonce = nonce + 1
    local data = fields or {}
    data.action = action
    data.request = tostring(noctalia.nowMs()) .. ":" .. tostring(nonce)
    noctalia.state.set("command", data)
end
function common.helper()
    return noctalia.pluginDir() .. "/controller.py"
end
return common
