from pathlib import Path

from ins_eagle_sync import gui
from ins_eagle_sync.config import load_config


def test_gui_module_exposes_main() -> None:
    assert callable(gui.main)


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


def test_sanitize_log_message_hides_cookie_path(project_tmp_path) -> None:
    secret = str(project_tmp_path / "instagram-cookies.txt")
    data = gui.default_config_data()
    data["cookies"]["file"] = secret

    message = gui.sanitize_log_message(f"cookies.file does not exist: {secret}", config_data=data)

    assert secret not in message
    assert "<hidden>" in message
