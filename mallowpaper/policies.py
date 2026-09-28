"""Pure policy/state reduction; no subprocesses or desktop mutations."""
DEFAULTS = {
    "pause_battery": False, "low_battery": 20, "pause_lock": True,
    "pause_suspend": True, "pause_fullscreen": True, "fullscreen_focused": False,
    "optimize": False, "slow_fps": False, "fps": 30, "height": 1080, "ac_only": True, "cache_mb": 2048,
}


def settings(values):
    result = dict(DEFAULTS)
    for key, value in values.items():
        if key not in result:
            raise ValueError(f"Unknown setting: {key}")
        if type(result[key]) is int and type(value) is float and value.is_integer():
            value = int(value)  # Luau has a single numeric type.
        if type(value) is not type(result[key]):
            raise ValueError(f"Invalid setting type: {key}")
        result[key] = value
    if result["fps"] not in (0, 15, 24, 30, 60):
        raise ValueError("Unsupported FPS cap")
    if result["height"] not in (0, 720, 1080, 1440, 2160):
        raise ValueError("Unsupported resolution bound")
    if not 0 <= result["low_battery"] <= 100 or not 128 <= result["cache_mb"] <= 16384:
        raise ValueError("Power/cache setting outside allowed range")
    return result


class NiriState:
    def __init__(self):
        self.windows, self.workspaces, self.outputs = {}, {}, {}
        self.overview = False
        self.connected = False

    def consume(self, message):
        if "WindowsChanged" in message:
            self.windows = {w["id"]: w for w in message["WindowsChanged"]["windows"]}
        elif "WorkspacesChanged" in message:
            self.workspaces = {w["id"]: w for w in message["WorkspacesChanged"]["workspaces"]}
        elif "WindowOpenedOrChanged" in message:
            window = message["WindowOpenedOrChanged"]["window"]
            if window.get("is_focused"):
                for current in self.windows.values():
                    current["is_focused"] = False
            self.windows[window["id"]] = window
        elif "WindowClosed" in message:
            self.windows.pop(message["WindowClosed"]["id"], None)
        elif "WindowFocusChanged" in message:
            focused = message["WindowFocusChanged"]["id"]
            for window in self.windows.values():
                window["is_focused"] = window["id"] == focused
        elif "WindowLayoutsChanged" in message:
            for key, layout in message["WindowLayoutsChanged"]["changes"]:
                if key in self.windows:
                    self.windows[key]["layout"] = layout
        elif "WorkspaceActivated" in message:
            change = message["WorkspaceActivated"]
            target = self.workspaces.get(change["id"])
            if target:
                for workspace in self.workspaces.values():
                    if workspace.get("output") == target.get("output"):
                        workspace["is_active"] = workspace["id"] == target["id"]
                    if change["focused"]:
                        workspace["is_focused"] = workspace["id"] == target["id"]
        elif "WorkspaceActiveWindowChanged" in message:
            change = message["WorkspaceActiveWindowChanged"]
            if change["workspace_id"] in self.workspaces:
                self.workspaces[change["workspace_id"]]["active_window_id"] = change["active_window_id"]
        elif "OverviewOpenedOrClosed" in message:
            self.overview = message["OverviewOpenedOrClosed"]["is_open"]
        else:
            return False
        return True

    def fullscreen_outputs(self, environment, focused_only=False):
        """Conservative Niri compatibility detection: explicit flag + active full tile.

        WLR has no stable identifier shared with Niri IPC. Only unique app/title
        matches are accepted. Tile bounds distinguish ordinary windowed fullscreen;
        they include Niri's black backdrop for fixed-size fullscreen clients.
        """
        if not self.connected or self.overview or not environment.get("foreign_available"):
            return set()
        found = set()
        for workspace in self.workspaces.values():
            if not workspace.get("is_active") or (focused_only and not workspace.get("is_focused")):
                continue
            output = workspace.get("output")
            window = self.windows.get(workspace.get("active_window_id"))
            logical = self.outputs.get(output, {}).get("logical")
            if not window or not logical or window.get("workspace_id") != workspace["id"]:
                continue
            if window.get("is_floating") or not window.get("title") or not window.get("app_id"):
                continue
            pair = (window["app_id"], window["title"])
            if sum((w.get("app_id"), w.get("title")) == pair for w in self.windows.values()) != 1:
                continue
            matches = [w for w in environment.get("toplevels", [])
                       if (w.get("app_id"), w.get("title")) == pair and output in w.get("outputs", [])]
            if len(matches) != 1 or not matches[0].get("fullscreen"):
                continue
            layout = window.get("layout", {})
            size = layout.get("tile_size", (0, 0))
            if abs(size[0] - logical["width"]) > 2 or abs(size[1] - logical["height"]) > 2:
                continue
            position = layout.get("tile_pos_in_workspace_view")
            if position is not None and (abs(position[0]) > 2 or abs(position[1]) > 2):
                continue
            found.add(output)
        return found


def pause_reasons(output, profile, config, environment, fullscreen):
    reasons = {"manual"} if profile.get("paused", False) else set()
    if environment.get("power_available") and environment.get("on_battery"):
        if profile.get("pause_battery", config["pause_battery"]):
            reasons.add("battery")
        percent = environment.get("percentage")
        if percent is not None and config["low_battery"] > 0 and percent <= config["low_battery"]:
            reasons.add("low_battery")
    if environment.get("session_available") and config["pause_lock"]:
        if environment.get("locked") or not environment.get("session_active", True):
            reasons.add("lock")
    if environment.get("sleeping") and config["pause_suspend"]:
        reasons.add("suspend")
    if profile.get("pause_fullscreen", config["pause_fullscreen"]) and output in fullscreen:
        reasons.add("fullscreen")
    return reasons
