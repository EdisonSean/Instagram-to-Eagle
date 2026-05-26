from __future__ import annotations

import sys
from pathlib import Path


APP_NAME = "Instagram to Eagle"
CONFIG_FILE_NAME = "config.json"
EXAMPLE_CONFIG_FILE_NAME = "config.example.json"
README_FILE_NAME = "README.md"
APP_ICON_RELATIVE_PATH = Path("assets") / "app_icon.ico"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_resource_path(relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    candidates = []

    if is_frozen():
        candidates.append(get_app_dir() / relative)
        bundle_dir = Path(getattr(sys, "_MEIPASS", get_app_dir()))
        candidates.append(bundle_dir / relative)
    else:
        candidates.append(get_project_root() / relative)
        candidates.append(get_app_dir() / relative)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def get_runtime_config_path() -> Path:
    return get_app_dir() / CONFIG_FILE_NAME if is_frozen() else Path(CONFIG_FILE_NAME)


def get_runtime_example_config_path() -> Path:
    return get_resource_path(EXAMPLE_CONFIG_FILE_NAME)


def get_runtime_readme_path() -> Path:
    return get_resource_path(README_FILE_NAME)
