import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mallowpaper"))
from policies import NiriState, pause_reasons, settings


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.state = NiriState()
        self.state.connected = True
        self.state.outputs = {name: {"logical": {"width": 1600, "height": 900}} for name in ("A", "B")}
        self.state.consume({"WorkspacesChanged": {"workspaces": [
            {"id": 1, "output": "A", "is_active": True, "is_focused": True, "active_window_id": 1},
            {"id": 2, "output": "A", "is_active": False, "is_focused": False, "active_window_id": 2},
            {"id": 3, "output": "B", "is_active": True, "is_focused": False, "active_window_id": 3}]}})
        self.state.consume({"WindowsChanged": {"windows": [
            {"id": i, "workspace_id": i, "app_id": "test", "title": str(i), "is_floating": False,
             "layout": {"tile_size": [1600, 900], "tile_pos_in_workspace_view": [0, 0],
                        "window_size": [640, 480], "window_offset_in_tile": [480, 210]}}
            for i in (1, 2, 3)]}})
        self.environment = {"foreign_available": True, "toplevels": [
            {"app_id": "test", "title": str(i), "outputs": ["B" if i == 3 else "A"], "fullscreen": True}
            for i in (1, 2, 3)]}

    def test_per_display_active_workspace_and_fixed_size_fullscreen(self):
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"A", "B"})
        self.assertEqual(self.state.fullscreen_outputs(self.environment, True), {"A"})
        self.state.consume({"WorkspaceActiveWindowChanged": {"workspace_id": 1, "active_window_id": None}})
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"B"})

    def test_hidden_workspace_and_scrolled_away_do_not_pause(self):
        self.environment["toplevels"][0]["fullscreen"] = False
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"B"})
        self.state.consume({"WorkspaceActivated": {"id": 2, "focused": True}})
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"A", "B"})
        self.state.windows[2]["layout"]["tile_pos_in_workspace_view"] = [600, 0]
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"B"})

    def test_windowed_fullscreen_and_maximized_rejected(self):
        self.state.windows[1]["layout"]["tile_size"] = [780, 850]
        self.environment["toplevels"][2]["fullscreen"] = False
        self.assertEqual(self.state.fullscreen_outputs(self.environment), set())

    def test_duplicate_titles_are_not_guessed(self):
        duplicate = copy.deepcopy(self.state.windows[1])
        duplicate["id"] = 9
        self.state.consume({"WindowOpenedOrChanged": {"window": duplicate}})
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"B"})
        self.state.consume({"WindowClosed": {"id": 9}})
        self.assertEqual(self.state.fullscreen_outputs(self.environment), {"A", "B"})

    def test_overview_and_disconnect_clear_fullscreen(self):
        self.state.consume({"OverviewOpenedOrClosed": {"is_open": True}})
        self.assertFalse(self.state.fullscreen_outputs(self.environment))
        self.state.consume({"OverviewOpenedOrClosed": {"is_open": False}})
        self.state.connected = False
        self.assertFalse(self.state.fullscreen_outputs(self.environment))

    def test_independent_power_and_manual_reasons(self):
        config = settings({"pause_battery": True})
        env = {"power_available": True, "on_battery": True, "percentage": 10,
               "session_available": True, "locked": True, "sleeping": True}
        reasons = pause_reasons("A", {"paused": True}, config, env, {"A"})
        self.assertEqual(reasons, {"manual", "battery", "low_battery", "lock", "suspend", "fullscreen"})
        self.assertEqual(pause_reasons("A", {"paused": True}, config, {}, set()), {"manual"})
        env.update(on_battery=False, locked=False, sleeping=False)
        self.assertEqual(pause_reasons("A", {}, config, env, set()), set())

    def test_output_overrides_and_validation(self):
        config = settings({"pause_battery": True, "fps": 15.0})
        env = {"power_available": True, "on_battery": True, "percentage": 95}
        self.assertFalse(pause_reasons("A", {"pause_battery": False, "pause_fullscreen": False}, config, env, {"A"}))
        for invalid in ({"fps": True}, {"fps": 999}, {"height": -1}, {"cache_mb": 1}):
            with self.assertRaises(ValueError):
                settings(invalid)


if __name__ == "__main__":
    unittest.main()
