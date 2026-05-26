import queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ins_eagle_sync import gui
from ins_eagle_sync.config import load_config
from ins_eagle_sync.ui_theme import APP_TITLE, COLORS


class FakeEntry:
    def __init__(self) -> None:
        self.value = ""
        self.state = "normal"

    def cget(self, key: str) -> str:
        if key == "state":
            return self.state
        raise KeyError(key)

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]

    def delete(self, start, end) -> None:
        self.value = ""

    def insert(self, index, value) -> None:
        self.value = str(value)

    def get(self) -> str:
        return self.value


class FakeUrlText:
    def __init__(self, value="") -> None:
        self.value = value

    def get(self, *_args) -> str:
        return self.value


class FakeChoice:
    def __init__(self, value="") -> None:
        self.value = value

    def set(self, value) -> None:
        self.value = value

    def get(self):
        return self.value


class FakeFrame:
    def __init__(self) -> None:
        self.visible = True
        self.propagate = True

    def grid(self, *args, **kwargs) -> None:
        self.visible = True

    def grid_remove(self) -> None:
        self.visible = False

    def grid_propagate(self, value) -> None:
        self.propagate = bool(value)


class FakeTextBox:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self.seen: list[str] = []
        self.yview_value = (0.0, 1.0)

    def insert(self, index, value, tag=None) -> None:
        self.lines.extend(value.splitlines())

    def delete(self, start, end) -> None:
        self.deleted.append((start, end))
        if start == "1.0" and end.endswith(".0"):
            count = int(end.split(".", 1)[0]) - 1
            del self.lines[:count]
        elif start == "1.0" and end == "end":
            self.lines.clear()

    def see(self, index) -> None:
        self.seen.append(index)

    def yview(self):
        return self.yview_value


class FakeCanvas:
    def __init__(self, *, height=102, width=320, y=0) -> None:
        self.height = height
        self.width = width
        self.y = y
        self.rectangles: list[tuple] = []
        self.texts: list[tuple] = []
        self.ovals: list[tuple] = []
        self.scrollregion = None
        self.scroll_calls: list[tuple[int, str]] = []
        self.moveto_calls: list[float] = []
        self.bindings = {}
        self.bbox_value = (0, 0, width, 1000)

    def delete(self, target) -> None:
        self.rectangles.clear()
        self.texts.clear()
        self.ovals.clear()

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def configure(self, **kwargs) -> None:
        if "scrollregion" in kwargs:
            self.scrollregion = kwargs["scrollregion"]

    def canvasy(self, y):
        return self.y + y

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))

    def create_text(self, *args, **kwargs):
        self.texts.append((args, kwargs))

    def create_oval(self, *args, **kwargs):
        self.ovals.append((args, kwargs))

    def yview_scroll(self, amount, units):
        self.scroll_calls.append((amount, units))

    def yview_moveto(self, fraction):
        value = float(fraction)
        self.moveto_calls.append(value)
        self.y = value * max(self.bbox_value[3], 1)

    def yview(self, *args):
        return None

    def bbox(self, target):
        return self.bbox_value

    def winfo_reqheight(self):
        return self.bbox_value[3]

    def bind(self, event, callback) -> None:
        self.bindings[event] = callback


class FakeWidget:
    def __init__(self, children=None, *, y=0, master=None, height=100) -> None:
        self.bindings = {}
        self.children = list(children or [])
        self.y = y
        self.master = master
        self.height = height
        self.options = {"border_color": gui.COLORS["border"], "border_width": 1}
        self.configures: list[dict] = []

    def bind(self, event, callback) -> None:
        self.bindings[event] = callback

    def winfo_children(self):
        return self.children

    def winfo_y(self):
        return self.y

    def winfo_height(self):
        return self.height

    def winfo_reqheight(self):
        return self.height

    def cget(self, key):
        return self.options.get(key)

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)
        self.configures.append(kwargs)


class FakeNavButton:
    def __init__(self) -> None:
        self.configures: list[dict] = []

    def configure(self, **kwargs) -> None:
        self.configures.append(kwargs)


class FakeWindow:
    def __init__(self, screen_width=1920, screen_height=1080) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.geometry_value = ""
        self.destroyed = False

    def update_idletasks(self) -> None:
        pass

    def winfo_screenwidth(self):
        return self.screen_width

    def winfo_screenheight(self):
        return self.screen_height

    def geometry(self, value) -> None:
        self.geometry_value = value

    def withdraw(self) -> None:
        pass

    def title(self, value) -> None:
        self.title_value = value

    def transient(self, parent) -> None:
        self.parent = parent

    def attributes(self, *args) -> None:
        self.attributes_value = args

    def deiconify(self) -> None:
        pass

    def lift(self) -> None:
        pass

    def destroy(self) -> None:
        self.destroyed = True


class RaisingBuildParent:
    def grid_columnconfigure(self, *args, **kwargs) -> None:
        raise AssertionError("builder should not touch parent when already built")

    def grid_rowconfigure(self, *args, **kwargs) -> None:
        raise AssertionError("builder should not touch parent when already built")


class FakeScrollableFrame:
    def __init__(self, children=None) -> None:
        self._parent_canvas = FakeCanvas()
        self.bindings = {}
        self.children = list(children or [])

    def bind(self, event, callback) -> None:
        self.bindings[event] = callback

    def winfo_children(self):
        return self.children


def test_gui_module_exposes_main() -> None:
    assert callable(gui.main)
    assert APP_TITLE == "Instagram to Eagle"
    assert COLORS["primary"]
    assert gui.MODE_POST == "单个帖子"
    assert gui.MODE_AUTHOR == "作者主页"
    assert gui.STATUS_READY == "就绪"
    assert gui.STATUS_RUNNING == "运行中"
    assert gui.LOG_PANEL_TITLE == "运行日志"


def test_resolve_config_path_falls_back_to_example(monkeypatch, project_tmp_path) -> None:
    monkeypatch.chdir(project_tmp_path)
    Path("config.example.json").write_text("{}", encoding="utf-8")

    assert gui.resolve_config_path("config.json") == Path("config.example.json")


def test_ensure_config_file_copies_example_when_config_is_missing(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    example_path = project_tmp_path / "config.example.json"
    example_data = gui.default_config_data()
    example_data["staging_dir"] = str(project_tmp_path / "stage")
    gui.write_config_data(example_data, example_path)

    result = gui.ensure_config_file(config_path, example_path)

    assert result == config_path
    assert config_path.exists()
    loaded = load_config(config_path)
    assert loaded.staging_dir == project_tmp_path / "stage"


def test_write_config_data_can_be_reloaded(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.default_config_data()
    data["eagle_api_base"] = "http://localhost:41596"
    data["default_eagle_root_folder"] = "Instagram/quinn.xyz"
    data["default_eagle_folder_path"] = "Instagram/quinn.xyz"
    data["default_eagle_folder_id"] = "folder-1"
    data["last_eagle_folder_path"] = "Instagram/last"
    data["last_eagle_folder_id"] = "last-1"
    data["cookies"]["file"] = str(project_tmp_path / "secret-cookies.txt")
    data["download"]["max_posts"] = 12

    gui.write_config_data(data, config_path)
    loaded_data = gui.load_config_data(config_path)
    loaded_config = load_config(config_path)

    assert loaded_data["eagle_api_base"] == "http://localhost:41596"
    assert loaded_config.default_eagle_root_folder == "Instagram/quinn.xyz"
    assert loaded_config.default_eagle_folder_path == "Instagram/quinn.xyz"
    assert loaded_config.default_eagle_folder_id == "folder-1"
    assert loaded_config.last_eagle_folder_path == "Instagram/last"
    assert loaded_config.last_eagle_folder_id == "last-1"
    assert loaded_config.download.max_posts == 12


def test_storage_parent_derives_runtime_paths(project_tmp_path) -> None:
    parent = project_tmp_path / "workspace"

    data = gui.apply_storage_parent(gui.default_config_data(), parent)

    assert data[gui.STORAGE_PARENT_KEY] == str(parent)
    assert data["staging_dir"] == str(parent / "_staging")
    assert data["archive_db"] == str(parent / "_cache" / "gallery-dl-archive.sqlite3")
    assert data["imported_state"] == str(parent / "_cache" / "eagle-imported.json")


def test_storage_parent_config_can_be_loaded(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    parent = project_tmp_path / "workspace"
    data = gui.apply_storage_parent(gui.default_config_data(), parent)

    gui.write_config_data(data, config_path)
    loaded = load_config(config_path)

    assert loaded.staging_dir == parent / "_staging"
    assert loaded.archive_db == parent / "_cache" / "gallery-dl-archive.sqlite3"
    assert loaded.imported_state == parent / "_cache" / "eagle-imported.json"


def test_old_proxy_config_migrates_to_manual_mode() -> None:
    data = gui.normalize_config_data(
        {
            "proxy": {
                "enabled": True,
                "http_proxy": "http://127.0.0.1:10809",
                "https_proxy": "http://127.0.0.1:10809",
            }
        }
    )

    assert data["proxy"]["mode"] == "manual"
    assert data["proxy"]["enabled"] is True


def test_proxy_mode_none_normalizes_to_disabled() -> None:
    data = gui.normalize_config_data({"proxy": {"mode": "none", "http_proxy": "http://old"}})

    assert data["proxy"]["mode"] == "none"
    assert data["proxy"]["enabled"] is False


def test_apply_proxy_settings_auto_saves_detected_proxy() -> None:
    data = gui.apply_proxy_settings(
        gui.default_config_data(),
        mode_label=gui.PROXY_AUTO,
        http_proxy="",
        https_proxy="",
        detected_result="当前检测结果：已检测到 http://127.0.0.1:10809",
    )

    assert data["proxy"]["mode"] == "auto"
    assert data["proxy"]["detected_proxy"] == "http://127.0.0.1:10809"
    assert data["proxy"]["http_proxy"] == ""


def test_apply_proxy_settings_manual_copies_http_to_https() -> None:
    data = gui.apply_proxy_settings(
        gui.default_config_data(),
        mode_label=gui.PROXY_MANUAL,
        http_proxy="127.0.0.1:10809",
        https_proxy="",
    )

    assert data["proxy"]["mode"] == "manual"
    assert data["proxy"]["http_proxy"] == "http://127.0.0.1:10809"
    assert data["proxy"]["https_proxy"] == "http://127.0.0.1:10809"


def test_apply_proxy_settings_none_clears_proxy() -> None:
    data = gui.apply_proxy_settings(
        gui.default_config_data(),
        mode_label=gui.PROXY_NONE,
        http_proxy="http://127.0.0.1:10809",
        https_proxy="http://127.0.0.1:10809",
    )

    assert data["proxy"]["mode"] == "none"
    assert data["proxy"]["enabled"] is False
    assert data["proxy"]["http_proxy"] == ""
    assert data["proxy"]["https_proxy"] == ""


def test_default_max_posts_is_unlimited() -> None:
    assert gui.default_config_data()["download"]["max_posts"] == -1


def test_sync_mode_keeps_reserved_author_slot_while_toggling_panel() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.author_options_slot = FakeFrame()
    app.author_options_panel = FakeFrame()
    app.recent_posts_frame = FakeFrame()
    app.date_options_frame = FakeFrame()
    app.author_range_choice = SimpleNamespace(get=lambda: gui.AUTHOR_SYNC_UNLIMITED)
    app.mode = SimpleNamespace(get=lambda: gui.MODE_POST)

    gui.InsEagleSyncApp._sync_mode_changed(app, gui.MODE_POST)
    assert app.author_options_slot.visible is True
    assert app.author_options_panel.visible is False

    gui.InsEagleSyncApp._sync_mode_changed(app, gui.MODE_AUTHOR)
    assert app.author_options_slot.visible is True
    assert app.author_options_panel.visible is True


def test_author_range_changed_only_shows_relevant_controls() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.recent_posts_frame = FakeFrame()
    app.date_options_frame = FakeFrame()
    app.author_range_choice = SimpleNamespace(get=lambda: gui.AUTHOR_SYNC_UNLIMITED)

    gui.InsEagleSyncApp._author_range_changed(app, gui.AUTHOR_SYNC_UNLIMITED)
    assert app.recent_posts_frame.visible is False
    assert app.date_options_frame.visible is False

    gui.InsEagleSyncApp._author_range_changed(app, gui.AUTHOR_SYNC_RECENT)
    assert app.recent_posts_frame.visible is True
    assert app.date_options_frame.visible is False

    gui.InsEagleSyncApp._author_range_changed(app, gui.AUTHOR_SYNC_DATE_RANGE)
    assert app.recent_posts_frame.visible is False
    assert app.date_options_frame.visible is True


def test_read_max_posts_accepts_unlimited_and_rejects_zero() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.max_posts_entry = FakeEntry()
    logs = []
    app._append_log = logs.append

    app.max_posts_entry.insert(0, "-1")
    assert gui.InsEagleSyncApp._read_max_posts(app) == -1

    app.max_posts_entry.delete(0, "end")
    app.max_posts_entry.insert(0, "0")
    assert gui.InsEagleSyncApp._read_max_posts(app) is False
    assert "必须是 -1 或大于 0" in logs[-1]


def test_read_author_sync_range_returns_matching_params() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.max_posts_entry = FakeEntry()
    app.anchor_date_entry = FakeEntry()
    app.date_range_amount_entry = FakeEntry()
    app.date_range_choice = SimpleNamespace(get=lambda: gui.DATE_RANGE_WEEK)
    logs = []
    app._append_log = logs.append

    app.max_posts_entry.insert(0, "12")
    app.anchor_date_entry.insert(0, "2026-05-25")
    app.date_range_amount_entry.insert(0, "2")

    app.author_range_choice = SimpleNamespace(get=lambda: gui.AUTHOR_SYNC_UNLIMITED)
    assert gui.InsEagleSyncApp._read_author_sync_range(app) == (-1, None, None)

    app.author_range_choice = SimpleNamespace(get=lambda: gui.AUTHOR_SYNC_RECENT)
    assert gui.InsEagleSyncApp._read_author_sync_range(app) == (12, None, None)

    app.author_range_choice = SimpleNamespace(get=lambda: gui.AUTHOR_SYNC_DATE_RANGE)
    assert gui.InsEagleSyncApp._read_author_sync_range(app) == (-1, "2026-05-12", "2026-05-26")


def test_author_date_range_uses_anchor_date_and_selected_window() -> None:
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_DAY) == ("2026-05-25", "2026-05-26")
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_WEEK) == ("2026-05-19", "2026-05-26")
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_MONTH) == ("2026-04-26", "2026-05-26")
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_YEAR) == ("2025-05-26", "2026-05-26")
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_DAY, 7) == ("2026-05-19", "2026-05-26")
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_WEEK, 2) == ("2026-05-12", "2026-05-26")
    assert gui.author_date_range("2026-05-25", gui.DATE_RANGE_MONTH, 3) == ("2026-02-26", "2026-05-26")


def test_read_date_range_uses_anchor_date_and_range_choice() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.anchor_date_entry = FakeEntry()
    app.date_range_amount_entry = FakeEntry()
    app.date_range_choice = SimpleNamespace(get=lambda: gui.DATE_RANGE_WEEK)

    app.anchor_date_entry.insert(0, "2026-05-25")
    app.date_range_amount_entry.insert(0, "2")

    assert gui.InsEagleSyncApp._read_date_range(app) == ("2026-05-12", "2026-05-26")


def test_browser_login_settings_write_from_browser(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_BROWSER,
        browser_label="Chrome",
        profile="Profile 2",
        cookie_file="",
    )

    gui.write_config_data(data, config_path)
    loaded = load_config(config_path)

    assert loaded.cookies.enabled is True
    assert loaded.cookies.from_browser == "chrome:Profile 2"
    assert loaded.cookies.file is None


def test_cookie_file_login_settings_write_cookie_path(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    cookie_path = project_tmp_path / "instagram-cookies.txt"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_COOKIE_FILE,
        browser_label="Chrome",
        profile="Default",
        cookie_file=str(cookie_path),
    )

    gui.write_config_data(data, config_path)
    loaded = load_config(config_path)

    assert loaded.cookies.enabled is True
    assert loaded.cookies.from_browser is None
    assert loaded.cookies.file == cookie_path


def test_no_login_settings_disable_cookies(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_NONE,
        browser_label="Chrome",
        profile="Default",
        cookie_file=str(project_tmp_path / "instagram-cookies.txt"),
    )

    gui.write_config_data(data, config_path)
    loaded = load_config(config_path)

    assert loaded.cookies.enabled is False
    assert loaded.cookies.from_browser is None
    assert loaded.cookies.file is None


def test_default_login_mode_is_no_login() -> None:
    method, browser_label, profile = gui.get_login_form_values(gui.default_config_data())

    assert method == gui.LOGIN_NONE
    assert browser_label == "Chrome"
    assert profile == "Default"


def test_center_window_uses_screen_center() -> None:
    window = FakeWindow(screen_width=1920, screen_height=1080)

    gui.center_window(window, 680, 420)

    assert window.geometry_value == "680x420+620+330"


def test_centered_warning_uses_centered_host(monkeypatch) -> None:
    host = FakeWindow(screen_width=1920, screen_height=1080)
    calls = []

    monkeypatch.setattr(gui.tk, "Toplevel", lambda parent: host)
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda **kwargs: calls.append(kwargs))

    gui.show_centered_warning(object(), "标题", "内容")

    assert host.geometry_value == "1x1+959+539"
    assert host.destroyed is True
    assert calls[0]["parent"] is host


def test_browser_cookie_failure_prompt_switches_to_cookie_file(monkeypatch) -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.login_method = FakeChoice(gui.LOGIN_BROWSER)
    app.changed_to = None
    app.help_opened = False
    app._login_method_changed = lambda value: setattr(app, "changed_to", value)
    app.show_cookie_help = lambda: setattr(app, "help_opened", True)
    warnings = []
    monkeypatch.setattr(gui, "show_centered_warning", lambda *args: warnings.append(args))

    gui.InsEagleSyncApp._show_browser_cookie_help_prompt(app)

    assert app.login_method.get() == gui.LOGIN_COOKIE_FILE
    assert app.changed_to == gui.LOGIN_COOKIE_FILE
    assert app.help_opened is True
    assert warnings


def test_url_text_helper_supports_multiline_textbox() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.url_entry = FakeUrlText(" https://www.instagram.com/p/ABC123/\nhttps://www.instagram.com/reel/DEF456/ \n")

    assert gui.InsEagleSyncApp._get_url_text(app) == (
        "https://www.instagram.com/p/ABC123/\nhttps://www.instagram.com/reel/DEF456/"
    )


def test_post_mode_multiple_urls_open_parent_unknown_staging_dir(project_tmp_path) -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.url_entry = FakeUrlText("https://www.instagram.com/p/ABC123/\nhttps://www.instagram.com/reel/DEF456/")
    app.config = SimpleNamespace(staging_dir=project_tmp_path / "staging")
    app.mode = FakeChoice(gui.MODE_POST)

    assert gui.InsEagleSyncApp._target_staging_dir(app) == project_tmp_path / "staging" / "unknown"


def test_run_sync_task_uses_multi_post_service_for_post_mode(project_tmp_path) -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.url_entry = FakeUrlText("https://www.instagram.com/p/ABC123/?img_index=1\nhttps://www.instagram.com/reel/DEF456/")
    app.folder_path_entry = FakeEntry()
    app.folder_path_entry.insert(0, "Instagram/posts")
    app.config = SimpleNamespace(eagle_api_base="http://localhost:41595")
    app.mode = FakeChoice(gui.MODE_POST)
    app.selected_folder_id = None
    app.dry_run_var = FakeChoice(False)
    app.force_var = FakeChoice(False)
    app.verify_var = FakeChoice(False)
    app.show_annotation_var = FakeChoice(False)
    app.ignore_archive_var = FakeChoice(True)
    app.cancel_event = SimpleNamespace(is_set=lambda: False)
    app._ensure_storage_parent_configured = lambda: True
    app._warn_about_cookies = lambda: None
    app._queue_log = lambda _message: None
    app._append_log = lambda _message: None
    started = []
    app._start_worker = lambda label, task: started.append((label, task()))

    with patch("ins_eagle_sync.gui.services.sync_posts", return_value={"ok": True, "messages": []}) as service_mock:
        gui.InsEagleSyncApp._run_sync_task(app, force_dry_run=False)

    assert started[0][0] == "同步"
    assert service_mock.call_args.args[1] == (
        "https://www.instagram.com/p/ABC123/\nhttps://www.instagram.com/reel/DEF456/"
    )
    assert service_mock.call_args.kwargs["folder_path"] == "Instagram/posts"
    assert service_mock.call_args.kwargs["ignore_archive"] is True
    assert service_mock.call_args.kwargs["cancel_event"] is app.cancel_event


def test_stop_sync_sets_cancel_event_and_disables_stop_button() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.worker = SimpleNamespace(is_alive=lambda: True)
    app.cancelled = False
    app.cancel_event = SimpleNamespace(set=lambda: setattr(app, "cancelled", True))
    app.stop_button = FakeNavButton()
    logs = []
    app._append_log = logs.append

    gui.InsEagleSyncApp.stop_sync(app)

    assert app.cancelled is True
    assert app.stop_button.configures[-1]["state"] == "disabled"
    assert any("停止" in message for message in logs)


def test_stop_button_uses_danger_style_while_running() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    for name in (
        "preview_button",
        "sync_button",
        "browse_folder_button",
        "folder_button",
        "open_staging_button",
        "open_config_button",
        "open_readme_button",
        "clear_log_button",
        "copy_log_button",
        "scan_profiles_button",
        "test_login_button",
        "save_settings_button",
        "reload_settings_button",
    ):
        setattr(app, name, FakeNavButton())
    app.stop_button = FakeNavButton()

    gui.InsEagleSyncApp._set_controls_enabled(app, False)

    assert app.stop_button.configures[-1]["state"] == "normal"
    assert app.stop_button.configures[-1]["fg_color"] == gui.COLORS["danger"]

    gui.InsEagleSyncApp._set_controls_enabled(app, True)

    assert app.stop_button.configures[-1]["state"] == "disabled"
    assert app.stop_button.configures[-1]["fg_color"] == gui.COLORS["surface_3"]


def test_window_icon_missing_does_not_crash(monkeypatch, project_tmp_path) -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.icon_status_message = None
    app.iconbitmap = lambda _path: None
    missing_icon = project_tmp_path / "missing.ico"
    monkeypatch.setattr(gui, "get_resource_path", lambda _relative: missing_icon)

    gui.InsEagleSyncApp._set_window_icon(app)

    assert "未找到应用图标" in app.icon_status_message


def test_scan_chrome_profiles_finds_cookie_databases(project_tmp_path) -> None:
    user_data = project_tmp_path / "Google" / "Chrome" / "User Data"
    (user_data / "Default" / "Network").mkdir(parents=True)
    (user_data / "Default" / "Network" / "Cookies").write_text("", encoding="utf-8")
    (user_data / "Profile 1").mkdir()
    (user_data / "Profile 1" / "Cookies").write_text("", encoding="utf-8")
    (user_data / "Profile 2" / "Network").mkdir(parents=True)
    (user_data / "Profile 2" / "Network" / "Cookies").write_text("", encoding="utf-8")
    (user_data / "System Profile").mkdir()

    profiles = gui.scan_browser_profiles("Chrome", local_appdata=project_tmp_path)

    assert profiles == ["Default", "Profile 1", "Profile 2"]


def test_scan_firefox_profiles_lists_profile_directories(project_tmp_path) -> None:
    profiles_root = project_tmp_path / "Mozilla" / "Firefox" / "Profiles"
    (profiles_root / "abc.default-release").mkdir(parents=True)
    (profiles_root / "xyz.dev").mkdir()

    profiles = gui.scan_browser_profiles("Firefox", appdata=project_tmp_path)

    assert profiles == ["abc.default-release", "xyz.dev"]


def test_sanitize_log_message_hides_cookie_path(project_tmp_path) -> None:
    secret = str(project_tmp_path / "instagram-cookies.txt")
    data = gui.default_config_data()
    data["cookies"]["file"] = secret

    message = gui.sanitize_log_message(f"cookies.file does not exist: {secret}", config_data=data)

    assert secret not in message
    assert "<hidden>" in message


def test_sanitize_log_message_hides_browser_profile() -> None:
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_BROWSER,
        browser_label="Chrome",
        profile="Profile 2",
        cookie_file="",
    )

    message = gui.sanitize_log_message("using chrome:Profile 2 / Profile 2", config_data=data)

    assert "Profile 2" not in message
    assert "<hidden>" in message


def test_login_check_hides_cookie_path(project_tmp_path) -> None:
    cookie_path = project_tmp_path / "instagram-cookies.txt"
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_COOKIE_FILE,
        browser_label="Chrome",
        profile="Default",
        cookie_file=str(cookie_path),
    )
    gui.write_config_data(data, config_path)
    config = load_config(config_path)
    completed = SimpleNamespace(returncode=4, stdout="", stderr=f"Failed to load {cookie_path}")

    with patch("ins_eagle_sync.gui.subprocess.run", return_value=completed):
        messages = gui.run_instagram_login_check(config)

    joined = "\n".join(messages)
    assert str(cookie_path) not in joined
    assert "<hidden>" in joined


def test_login_check_no_login_mode_omits_cookie_args(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_NONE,
        browser_label="Chrome",
        profile="Default",
        cookie_file="",
    )
    gui.write_config_data(data, config_path)
    config = load_config(config_path)

    command = gui.build_login_check_command(config, "https://www.instagram.com/instagram/")

    assert "--cookies" not in command
    assert "--cookies-from-browser" not in command


def test_login_check_browser_command_log_hides_profile(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_BROWSER,
        browser_label="Chrome",
        profile="Profile 2",
        cookie_file="",
    )
    gui.write_config_data(data, config_path)
    config = load_config(config_path)
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("ins_eagle_sync.gui.subprocess.run", return_value=completed):
        messages = gui.run_instagram_login_check(config)

    joined = "\n".join(messages)
    assert "Profile 2" not in joined
    assert "--cookies-from-browser <hidden>" in joined


def test_browser_login_check_failure_suggests_closing_browser(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_BROWSER,
        browser_label="Chrome",
        profile="Default",
        cookie_file="",
    )
    gui.write_config_data(data, config_path)
    config = load_config(config_path)
    completed = SimpleNamespace(
        returncode=4,
        stdout="",
        stderr="[cookies][warning] Failed to decrypt cookie (DPAPI)",
    )

    with patch("ins_eagle_sync.gui.subprocess.run", return_value=completed):
        messages = gui.run_instagram_login_check(config)

    assert any("关闭浏览器后重试" in message for message in messages)


def test_login_redirect_generates_friendly_hint(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    data = gui.apply_login_settings(
        gui.default_config_data(),
        method=gui.LOGIN_COOKIE_FILE,
        browser_label="Chrome",
        profile="Default",
        cookie_file=str(project_tmp_path / "instagram-cookies.txt"),
    )
    gui.write_config_data(data, config_path)
    config = load_config(config_path)
    completed = SimpleNamespace(
        returncode=4,
        stdout="",
        stderr="[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)",
    )

    with patch("ins_eagle_sync.gui.subprocess.run", return_value=completed):
        messages = gui.run_instagram_login_check(config)

    assert any(gui.FRIENDLY_LOGIN_FAILURE_HINT in message for message in messages)


def test_startup_checks_hide_cookie_path_and_mock_external_checks(project_tmp_path) -> None:
    cookie_path = project_tmp_path / "instagram-cookies.txt"
    cookie_path.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    config_path = project_tmp_path / "config.json"
    data = gui.default_config_data()
    data["cookies"]["enabled"] = True
    data["cookies"]["file"] = str(cookie_path)
    gui.write_config_data(data, config_path)
    config = load_config(config_path)

    fake_eagle = type("FakeEagle", (), {"check_app_available": lambda self: True})()
    completed = SimpleNamespace(returncode=0, stdout="1.29.0\n", stderr="")

    with (
        patch("ins_eagle_sync.gui.EagleClient", return_value=fake_eagle),
        patch("ins_eagle_sync.gui.resolve_gallery_dl_command", return_value=["py", "-m", "gallery_dl"]),
        patch("ins_eagle_sync.gui.resolve_ytdlp_command", return_value=["py", "-m", "yt_dlp"]),
        patch("ins_eagle_sync.gui.subprocess.run", return_value=completed),
    ):
        messages = gui.run_startup_checks(config)

    joined = "\n".join(messages)
    assert str(cookie_path) not in joined
    assert "<hidden>" in joined
    assert "Eagle 本地 API 可以连接" in joined
    assert "gallery-dl Python 模块可用" in joined


def test_startup_checks_report_packaged_gallery_and_optional_ytdlp(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    gui.write_config_data(gui.default_config_data(), config_path)
    config = load_config(config_path)
    fake_eagle = type("FakeEagle", (), {"check_app_available": lambda self: True})()
    gallery_exe = project_tmp_path / "tools" / "gallery-dl.exe"
    gallery_exe.parent.mkdir()
    gallery_exe.write_bytes(b"")

    with (
        patch("ins_eagle_sync.gui.EagleClient", return_value=fake_eagle),
        patch("ins_eagle_sync.gui.resolve_gallery_dl_command", return_value=[str(gallery_exe)]),
        patch("ins_eagle_sync.gui.resolve_ytdlp_command", return_value=None),
        patch("ins_eagle_sync.gui.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="1.29.0\n", stderr="")),
    ):
        messages = gui.run_startup_checks(config)

    joined = "\n".join(messages)
    assert "已找到内置 gallery-dl.exe" in joined
    assert "未找到 yt-dlp" in joined


def test_startup_checks_report_bundled_gallery_module(project_tmp_path) -> None:
    config_path = project_tmp_path / "config.json"
    gui.write_config_data(gui.default_config_data(), config_path)
    config = load_config(config_path)
    fake_eagle = type("FakeEagle", (), {"check_app_available": lambda self: True})()
    internal_command = [str(project_tmp_path / "Instagram to Eagle.exe"), gui.FROZEN_GALLERY_DL_MODULE_ARG]

    with (
        patch("ins_eagle_sync.gui.EagleClient", return_value=fake_eagle),
        patch("ins_eagle_sync.gui.resolve_gallery_dl_command", return_value=internal_command),
        patch("ins_eagle_sync.gui.resolve_ytdlp_command", return_value=None),
        patch("ins_eagle_sync.gui.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="1.32.1\n", stderr="")),
    ):
        messages = gui.run_startup_checks(config)

    joined = "\n".join(messages)
    assert "已内置 gallery-dl Python 模块" in joined


def test_gallery_dl_check_failure_is_nonfatal() -> None:
    with patch("ins_eagle_sync.gui.subprocess.run", side_effect=FileNotFoundError("missing")):
        ok, message = gui.check_gallery_dl_available("missing-gallery-dl")

    assert ok is False
    assert "gallery-dl 不可用" in message


def test_log_message_classification() -> None:
    assert gui.classify_log_message("正常：ready") == "ok"
    assert gui.classify_log_message("警告：check cookies") == "warning"
    assert gui.classify_log_message("错误：failed") == "error"


def test_log_queue_flushes_in_batches_and_trims() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.log_queue = queue.Queue()
    app.log_text = FakeTextBox()
    app.log_line_count = gui.MAX_LOG_LINES - 1
    app.config_data = gui.default_config_data()
    app.config = None
    after_calls = []
    app.after = lambda delay, callback: after_calls.append((delay, callback))
    app._set_controls_enabled = lambda _enabled: None
    app._set_status = lambda _status: None

    for index in range(3):
        app.log_queue.put(f"line {index}")

    gui.InsEagleSyncApp._drain_log_queue(app)

    assert app.log_text.lines == ["line 2"]
    assert app.log_line_count == gui.MAX_LOG_LINES
    assert app.log_text.deleted
    assert after_calls[0][0] == gui.LOG_FLUSH_INTERVAL_MS


def test_resize_defers_log_queue_flush() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app._is_resizing = True
    app._resize_debug_enabled = True
    app.resize_debug_stats = {"root_configure_events": 0, "log_flush_deferred": 0}
    app.log_queue = queue.Queue()
    app.log_queue.put("line")
    app.log_text = FakeTextBox()
    after_calls = []
    app.after = lambda delay, callback: after_calls.append((delay, callback))

    gui.InsEagleSyncApp._drain_log_queue(app)

    assert app.log_text.lines == []
    assert app.log_queue.qsize() == 1
    assert app.resize_debug_stats["log_flush_deferred"] == 1
    assert after_calls[0][0] == gui.LOG_FLUSH_RESIZE_DELAY_MS


def test_root_configure_only_debounces_resize_state() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app._resize_debug_enabled = True
    app.resize_debug_stats = {"root_configure_events": 0, "log_flush_deferred": 0}
    app._resize_after_id = "old"
    cancelled = []
    scheduled = []
    app.after_cancel = lambda after_id: cancelled.append(after_id)
    app.after = lambda delay, callback: scheduled.append((delay, callback)) or "new"

    gui.InsEagleSyncApp._on_root_configure(app, SimpleNamespace(widget=app))

    assert app._is_resizing is True
    assert app.resize_debug_stats["root_configure_events"] == 1
    assert cancelled == ["old"]
    assert scheduled[0][0] == gui.RESIZE_IDLE_DEBOUNCE_MS


def test_tab_builders_are_guarded_against_duplicate_builds() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app._sync_tab_built = True
    app._settings_tab_built = True

    gui.InsEagleSyncApp._build_sync_tab(app, RaisingBuildParent())
    gui.InsEagleSyncApp._build_settings_tab(app, RaisingBuildParent())


def test_main_scrollable_frame_mousewheel_uses_larger_step() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    frame = FakeScrollableFrame()

    gui.InsEagleSyncApp._bind_scrollable_frame_mousewheel(app, frame)
    result = frame.bindings["<MouseWheel>"](SimpleNamespace(delta=-120))

    assert result == "break"
    assert frame._parent_canvas.scroll_calls == [(gui.MAIN_SCROLL_UNITS_PER_WHEEL, "units")]


def test_main_scrollable_frame_child_mousewheel_uses_same_step() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    child = FakeWidget()
    frame = FakeScrollableFrame(children=[FakeWidget(children=[child])])

    gui.InsEagleSyncApp._bind_scrollable_frame_mousewheel(app, frame)
    result = child.bindings["<MouseWheel>"](SimpleNamespace(delta=-120))

    assert result == "break"
    assert frame._parent_canvas.scroll_calls == [(gui.MAIN_SCROLL_UNITS_PER_WHEEL, "units")]


def test_settings_section_scroll_helper_updates_highlight() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    canvas = FakeCanvas(height=400, y=0)
    canvas.bbox_value = (0, 0, 600, 1200)
    app.settings_tab = SimpleNamespace(_parent_canvas=canvas)
    app.settings_nav_after_id = None
    app.after = lambda _delay, callback: callback()
    app.after_cancel = lambda _after_id: None
    app.update_idletasks = lambda: None
    content = FakeWidget(y=0)
    instagram = FakeWidget(y=160, master=content)
    storage = FakeWidget(y=520, master=content)
    proxy = FakeWidget(y=840, master=content)
    app.settings_content_frame = content
    app.settings_nav_order = (
        ("instagram", "Instagram 登录"),
        ("storage", "下载与缓存"),
        ("proxy", "代理设置"),
    )
    app.settings_section_widgets = {
        "instagram": instagram,
        "storage": storage,
        "proxy": proxy,
    }
    app.settings_nav_buttons = {key: FakeNavButton() for key, _label in app.settings_nav_order}

    gui.InsEagleSyncApp._scroll_settings_to_section(app, "storage")

    assert canvas.moveto_calls
    assert app.settings_nav_buttons["storage"].configures[-1]["fg_color"] == gui.COLORS["selection"]

    canvas.y = 850
    gui.InsEagleSyncApp._update_settings_nav_from_scroll(app)

    assert app.settings_nav_buttons["proxy"].configures[-1]["fg_color"] == gui.COLORS["selection"]


def test_settings_section_active_helper_uses_bottom_section_when_scrolled_to_end() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    canvas = FakeCanvas(height=400, y=800)
    canvas.bbox_value = (0, 0, 600, 1200)
    app.settings_tab = SimpleNamespace(_parent_canvas=canvas)
    app.settings_nav_after_id = None
    content = FakeWidget(y=0)
    instagram = FakeWidget(y=160, master=content, height=260)
    storage = FakeWidget(y=520, master=content, height=180)
    eagle = FakeWidget(y=740, master=content, height=380)
    proxy = FakeWidget(y=180, master=eagle, height=150)
    app.settings_content_frame = content
    app.settings_nav_order = (
        ("instagram", "Instagram"),
        ("storage", "Storage"),
        ("eagle", "Eagle"),
        ("proxy", "Proxy"),
    )
    app.settings_section_widgets = {
        "instagram": instagram,
        "storage": storage,
        "eagle": eagle,
        "proxy": proxy,
    }

    active = gui.InsEagleSyncApp._settings_active_section_key(app)

    assert active == "proxy"


def test_settings_nav_update_is_noop_without_left_preferences_nav() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.settings_nav_buttons = {}
    app.settings_nav_after_id = None
    app.after = lambda _delay, _callback: (_ for _ in ()).throw(AssertionError("no nav update expected"))

    gui.InsEagleSyncApp._schedule_settings_nav_update(app)

    assert app.settings_nav_after_id is None


def test_settings_section_flash_uses_primary_border_then_restores() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    target = FakeWidget()
    app.settings_section_widgets = {"storage": target}
    callbacks = []
    app.after = lambda _delay, callback: callbacks.append(callback)

    gui.InsEagleSyncApp._flash_settings_section(app, "storage")

    assert target.configures[-1]["border_color"] == gui.COLORS["primary_soft"]
    callbacks[0]()
    assert target.configures[-1]["border_color"] == gui.COLORS["primary"]
    callbacks[-1]()
    assert target.configures[-1]["border_color"] == gui.COLORS["border"]


def test_folder_picker_search_debounce_is_200ms() -> None:
    assert gui.FOLDER_SEARCH_DEBOUNCE_MS == 200


def test_folder_picker_draw_tree_only_draws_visible_rows() -> None:
    dialog = object.__new__(gui.EagleFolderPickerDialog)
    dialog.tree_canvas = FakeCanvas(height=gui.FOLDER_ROW_HEIGHT * 3, y=gui.FOLDER_ROW_HEIGHT * 50)
    dialog.visible_rows = [
        {"folder": {"id": f"folder-{index}", "name": f"Folder {index}", "path": f"Folder {index}"}, "depth": 0}
        for index in range(100)
    ]
    dialog.selected_folder = None
    dialog.hover_row_index = None
    dialog.children_by_parent = {}
    dialog.expanded_folder_ids = set()

    gui.EagleFolderPickerDialog._draw_tree(dialog)

    assert len(dialog.tree_canvas.rectangles) < len(dialog.visible_rows)
    assert len(dialog.tree_canvas.rectangles) <= 13


def test_folder_picker_rows_support_tree_and_search() -> None:
    folders = [
        {"id": "root-1", "name": "Instagram", "path": "Instagram", "parent_id": None, "icon": "award3"},
        {"id": "child-1", "name": "quinn.xyz", "path": "Instagram/quinn.xyz", "parent_id": "root-1", "icon": "tree"},
        {"id": "cg-1", "name": "CG", "path": "CG", "parent_id": None, "icon": "briefcase"},
        {"id": "other-1", "name": "reference", "path": "CG/houdini/reference", "parent_id": "cg-1"},
    ]

    tree_rows = gui.folder_picker_rows(folders)
    expanded_rows = gui.folder_picker_rows(folders, expanded_ids={"root-1"})
    collapsed_again_rows = gui.folder_picker_rows(folders, expanded_ids=set())
    search_rows = gui.folder_picker_rows(folders, "houdini")

    assert [row["folder"]["name"] for row in tree_rows] == ["Instagram", "CG"]
    assert [row["folder"]["name"] for row in expanded_rows] == ["Instagram", "quinn.xyz", "CG"]
    assert [row["folder"]["name"] for row in collapsed_again_rows] == ["Instagram", "CG"]
    assert [row["folder"]["path"] for row in search_rows] == ["CG/houdini/reference"]
    assert search_rows[0]["search"] is True


def test_folder_picker_display_uses_name_not_raw_icon() -> None:
    folder = {
        "id": "folder-1",
        "name": "Real Folder",
        "path": "Instagram/Real Folder",
        "icon": "award3",
        "icon_color": "#ff0000",
    }

    tree_text = gui.format_folder_row_text({"folder": folder, "depth": 0, "search": False})
    search_text = gui.format_folder_row_text({"folder": folder, "depth": 0, "search": True})

    assert "Real Folder" in tree_text
    assert "Instagram/Real Folder" in search_text
    assert "award3" not in tree_text
    assert "award3" not in search_text


def test_folder_row_arrow_uses_modern_triangles() -> None:
    folder = {"id": "root-1", "name": "Instagram"}

    assert gui.folder_row_arrow(folder, expanded_ids=set(), search=False, has_children=True) == "▸"
    assert gui.folder_row_arrow(folder, expanded_ids={"root-1"}, search=False, has_children=True) == "▾"
    assert gui.folder_row_arrow(folder, expanded_ids={"root-1"}, search=True, has_children=True) == ""
    assert gui.folder_row_arrow(folder, expanded_ids=set(), search=False, has_children=False) == ""


def test_folder_children_index_supports_parent_links() -> None:
    folders = [
        {"id": "root-1", "name": "Instagram", "path": "Instagram", "parent_id": None},
        {"id": "child-1", "name": "quinn.xyz", "path": "Instagram/quinn.xyz", "parent_id": "root-1"},
    ]

    children = gui.folder_children_index(folders)

    assert children[None][0]["id"] == "root-1"
    assert children["root-1"][0]["id"] == "child-1"


def test_folder_selection_result_returns_id_and_path() -> None:
    folder = {"id": "child-1", "name": "quinn.xyz", "path": "Instagram/quinn.xyz"}

    assert gui.folder_selection_result(folder) == {
        "folder_id": "child-1",
        "folder_path": "Instagram/quinn.xyz",
    }


def test_gui_sync_folder_selection_updates_entry_and_id() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.folder_path_entry = FakeEntry()
    app.selected_folder_id = None
    logs = []
    app._append_log = logs.append

    gui.InsEagleSyncApp._apply_sync_folder_selection(
        app,
        {"folder_id": "child-1", "folder_path": "Instagram/quinn.xyz"},
    )

    assert app.folder_path_entry.get() == "Instagram/quinn.xyz"
    assert app.selected_folder_id == "child-1"
    assert logs[-1] == "已选择 Eagle 文件夹：Instagram/quinn.xyz"


def test_gui_manual_sync_folder_edit_clears_selected_id() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.selected_folder_id = "child-1"

    gui.InsEagleSyncApp._sync_folder_path_changed(app)

    assert app.selected_folder_id is None


def test_gui_default_folder_selection_updates_entry_and_id() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.setting_entries = {"default_folder_path": FakeEntry()}
    app.selected_default_folder_id = None
    logs = []
    app._append_log = logs.append

    gui.InsEagleSyncApp._apply_default_folder_selection(
        app,
        {"folder_id": "default-1", "folder_path": "Instagram/default"},
    )

    assert app.setting_entries["default_folder_path"].get() == "Instagram/default"
    assert app.selected_default_folder_id == "default-1"


def test_gui_manual_default_folder_edit_clears_selected_id() -> None:
    app = object.__new__(gui.InsEagleSyncApp)
    app.selected_default_folder_id = "default-1"

    gui.InsEagleSyncApp._default_folder_path_changed(app)

    assert app.selected_default_folder_id is None


def test_folder_picker_error_message_is_user_friendly() -> None:
    message = gui.folder_picker_error_message(["Eagle Local API folder list request failed: connection refused"])

    assert message == "无法读取 Eagle 文件夹，请确认 Eagle 已打开并且本地 API 地址正确。"


def test_last_folder_overrides_default_folder_for_sync_entry() -> None:
    data = gui.default_config_data()
    data["default_eagle_folder_path"] = "Instagram/default"
    data["default_eagle_folder_id"] = "default-1"
    data["last_eagle_folder_path"] = "Instagram/last"
    data["last_eagle_folder_id"] = "last-1"

    assert gui.get_last_or_default_folder(data) == {
        "folder_path": "Instagram/last",
        "folder_id": "last-1",
    }


def test_last_folder_falls_back_to_default_folder() -> None:
    data = gui.default_config_data()
    data["default_eagle_folder_path"] = "Instagram/default"
    data["default_eagle_folder_id"] = "default-1"
    data["last_eagle_folder_path"] = ""
    data["last_eagle_folder_id"] = ""

    assert gui.get_last_or_default_folder(data) == {
        "folder_path": "Instagram/default",
        "folder_id": "default-1",
    }


def test_apply_last_eagle_folder_updates_config_data() -> None:
    data = gui.apply_last_eagle_folder(
        gui.default_config_data(),
        {"folder_id": "last-1", "folder_path": "Instagram/last"},
    )

    assert data["last_eagle_folder_path"] == "Instagram/last"
    assert data["last_eagle_folder_id"] == "last-1"
