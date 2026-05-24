from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ins_eagle_sync import gui
from ins_eagle_sync.config import load_config


def test_gui_module_exposes_main() -> None:
    assert callable(gui.main)
    assert gui.MODE_POST == "单个帖子"
    assert gui.MODE_AUTHOR == "作者主页"
    assert gui.STATUS_READY == "就绪"
    assert gui.STATUS_RUNNING == "运行中"


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
    data["cookies"]["file"] = str(project_tmp_path / "secret-cookies.txt")
    data["download"]["max_posts"] = 12

    gui.write_config_data(data, config_path)
    loaded_data = gui.load_config_data(config_path)
    loaded_config = load_config(config_path)

    assert loaded_data["eagle_api_base"] == "http://localhost:41596"
    assert loaded_config.default_eagle_root_folder == "Instagram/quinn.xyz"
    assert loaded_config.download.max_posts == 12


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
        patch("ins_eagle_sync.gui.subprocess.run", return_value=completed),
    ):
        messages = gui.run_startup_checks(config)

    joined = "\n".join(messages)
    assert str(cookie_path) not in joined
    assert "<hidden>" in joined
    assert "Eagle 本地 API 可以连接" in joined
    assert "gallery-dl 可用" in joined


def test_gallery_dl_check_failure_is_nonfatal() -> None:
    with patch("ins_eagle_sync.gui.subprocess.run", side_effect=FileNotFoundError("missing")):
        ok, message = gui.check_gallery_dl_available("missing-gallery-dl")

    assert ok is False
    assert "gallery-dl 不可用" in message
