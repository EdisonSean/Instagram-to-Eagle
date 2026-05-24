from pathlib import Path

from ins_eagle_sync import gui


def test_gui_module_exposes_main() -> None:
    assert callable(gui.main)


def test_resolve_config_path_falls_back_to_example(monkeypatch, project_tmp_path) -> None:
    monkeypatch.chdir(project_tmp_path)
    Path("config.example.json").write_text("{}", encoding="utf-8")

    assert gui.resolve_config_path("config.json") == Path("config.example.json")
