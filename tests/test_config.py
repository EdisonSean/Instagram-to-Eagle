import sys
from pathlib import Path

from ins_eagle_sync.config import (
    FROZEN_GALLERY_DL_MODULE_ARG,
    parse_config,
    resolve_gallery_dl_command,
    resolve_ytdlp_command,
)
from ins_eagle_sync.runtime import get_app_dir, get_resource_path


def make_config_data() -> dict:
    return {
        "gallery_dl_executable": "py -m gallery_dl",
        "staging_dir": "E:/INS_Eagle_Sync/_staging",
        "archive_db": "E:/INS_Eagle_Sync/_cache/gallery-dl-archive.sqlite3",
        "imported_state": "E:/INS_Eagle_Sync/_cache/eagle-imported.json",
        "eagle_api_base": "http://localhost:41595",
        "default_eagle_root_folder": "Instagram",
        "title_caption_chars": 70,
        "proxy": {"mode": "none"},
        "cookies": {"enabled": False},
        "download": {"sleep_request": "8-15", "max_posts": -1},
    }


def test_packaged_app_prefers_tools_gallery_dl_exe(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "dist" / "Instagram to Eagle"
    tools_dir = app_dir / "tools"
    tools_dir.mkdir(parents=True)
    gallery_dl_exe = tools_dir / "gallery-dl.exe"
    gallery_dl_exe.write_bytes(b"")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "Instagram to Eagle.exe"))

    config = parse_config(make_config_data())

    assert get_app_dir() == app_dir
    assert resolve_gallery_dl_command(config) == [str(gallery_dl_exe)]


def test_packaged_app_respects_custom_gallery_dl_command(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "dist" / "Instagram to Eagle"
    tools_dir = app_dir / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "gallery-dl.exe").write_bytes(b"")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "Instagram to Eagle.exe"))
    data = make_config_data()
    data["gallery_dl_executable"] = "C:/portable/gallery-dl.exe"

    config = parse_config(data)

    assert resolve_gallery_dl_command(config) == ["C:/portable/gallery-dl.exe"]


def test_packaged_app_falls_back_to_bundled_gallery_dl_module(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "dist" / "Instagram to Eagle"
    app_dir.mkdir(parents=True)
    exe = app_dir / "Instagram to Eagle.exe"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    config = parse_config(make_config_data())

    assert resolve_gallery_dl_command(config) == [str(exe), FROZEN_GALLERY_DL_MODULE_ARG]


def test_dev_environment_can_fallback_to_py_gallery_dl(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    config = parse_config(make_config_data())

    assert resolve_gallery_dl_command(config) == ["py", "-m", "gallery_dl"]


def test_tools_ytdlp_exe_is_detected_in_packaged_app(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "dist" / "Instagram to Eagle"
    tools_dir = app_dir / "tools"
    tools_dir.mkdir(parents=True)
    ytdlp_exe = tools_dir / "yt-dlp.exe"
    ytdlp_exe.write_bytes(b"")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "Instagram to Eagle.exe"))

    config = parse_config(make_config_data())

    assert resolve_ytdlp_command(config) == [str(ytdlp_exe)]


def test_ytdlp_missing_is_optional_in_packaged_app(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "dist" / "Instagram to Eagle"
    app_dir.mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "Instagram to Eagle.exe"))

    config = parse_config(make_config_data())

    assert resolve_ytdlp_command(config) is None


def test_resource_paths_resolve_in_dev_environment(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert get_resource_path("README.md").exists()
    assert get_resource_path("config.example.json").exists()
    assert get_resource_path("assets/app_icon.ico").exists()


def test_resource_paths_resolve_in_packaged_app(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "dist" / "Instagram to Eagle"
    assets_dir = app_dir / "assets"
    assets_dir.mkdir(parents=True)
    readme = app_dir / "README.md"
    example = app_dir / "config.example.json"
    icon = assets_dir / "app_icon.ico"
    readme.write_text("readme", encoding="utf-8")
    example.write_text("{}", encoding="utf-8")
    icon.write_bytes(b"icon")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "Instagram to Eagle.exe"))

    assert get_resource_path("README.md") == readme
    assert get_resource_path("config.example.json") == example
    assert get_resource_path("assets/app_icon.ico") == icon


def test_build_script_copies_release_assets_but_not_user_data() -> None:
    script = Path("scripts/build_exe.ps1").read_text(encoding="utf-8")

    assert "Instagram to Eagle" in script
    assert "config.example.json" in script
    assert "README.md" in script
    assert "tools\\gallery-dl.exe" in script
    assert "tools\\yt-dlp.exe" in script
    assert "--icon" in script
    assert "assets\\app_icon.ico" in script
    assert "--collect-all\", \"gallery_dl" in script
    assert "--hidden-import\", \"gallery_dl" in script
    assert "--hidden-import\", \"gallery_dl.__main__" in script
    assert "--collect-submodules\", \"gallery_dl.extractor" in script
    assert "--collect-submodules\", \"gallery_dl.downloader" in script
    assert "--collect-submodules\", \"gallery_dl.postprocessor" in script
    assert "FROZEN_GALLERY_DL_MODULE_ARG" in script
    assert "gallery_dl.main()" in script
    assert "$MinimumGalleryDlVersion = [version]\"1.32.1\"" in script
    assert "py -m gallery_dl --version" in script
    assert "Bundling gallery_dl Python module version" in script
    assert "IncludeExternalGalleryDl" in script
    assert "-AllowPathLookup $false" in script
    assert "Remove-Item -Force -Path $staleGalleryDl" in script
    assert "ForceCloseRunningApp" in script
    assert "Get-RunningPackagedApp" in script
    assert "旧版 Instagram to Eagle 仍在运行" in script
    assert "Remove-Item -LiteralPath $DistAppDir -Recurse -Force" in script
    assert "Copy-Item -Force -Path (Join-Path $RepoRoot \"config.json\")" not in script
    assert "cookies.txt" not in script
    assert "_cache" not in script
    assert "_staging" not in script
