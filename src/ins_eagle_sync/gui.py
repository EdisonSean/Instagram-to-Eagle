from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import traceback
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency hint for GUI users.
    ctk = None  # type: ignore[assignment]

from . import services
from .config import AppConfig, load_config
from .eagle_client import EagleClient
from .utils import InstagramMode, detect_instagram_url


DEFAULT_CONFIG_PATH = "config.json"
EXAMPLE_CONFIG_PATH = "config.example.json"
MODE_POST = "单帖 sync-post"
MODE_AUTHOR = "作者 sync-author"
SYNC_TAB_NAME = "同步"
SETTINGS_TAB_NAME = "设置"
DEFAULT_FOLDER_PATH = "Instagram/quinn.xyz"
STATUS_READY = "Ready"
STATUS_RUNNING = "Running"
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"

DEFAULT_CONFIG_DATA: dict[str, Any] = {
    "gallery_dl_executable": "py -m gallery_dl",
    "staging_dir": "E:/INS_Eagle_Sync/_staging",
    "archive_db": "E:/INS_Eagle_Sync/_cache/gallery-dl-archive.sqlite3",
    "imported_state": "E:/INS_Eagle_Sync/_cache/eagle-imported.json",
    "eagle_api_base": "http://localhost:41595",
    "default_eagle_root_folder": DEFAULT_FOLDER_PATH,
    "title_caption_chars": 70,
    "proxy": {
        "enabled": True,
        "http_proxy": "http://127.0.0.1:10809",
        "https_proxy": "http://127.0.0.1:10809",
    },
    "cookies": {
        "enabled": False,
        "from_browser": "",
        "file": "E:/INS_Eagle_Sync/_cache/instagram-cookies.txt",
    },
    "download": {
        "sleep_request": "8-15",
        "max_posts": 50,
    },
}

_BaseWindow = ctk.CTk if ctk is not None else object


class InsEagleSyncApp(_BaseWindow):
    def __init__(self) -> None:
        super().__init__()
        self.title("ins-eagle-sync")
        self.geometry("1040x760")
        self.minsize(900, 660)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.setting_entries: dict[str, Any] = {}
        self.status_var = ctk.StringVar(value=STATUS_READY)
        self.config_path = ensure_config_file(DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH)
        self.config_data = load_config_data(self.config_path)
        self.config = self._load_config()

        self._build_layout()
        self._set_default_values()
        self.after(100, self._drain_log_queue)
        self.after(250, self.startup_checks)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.sync_tab = self.tabview.add(SYNC_TAB_NAME)
        self.settings_tab = self.tabview.add(SETTINGS_TAB_NAME)

        self._build_sync_tab(self.sync_tab)
        self._build_settings_tab(self.settings_tab)

        status_bar = ctk.CTkFrame(self, corner_radius=0)
        status_bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        ctk.CTkLabel(status_bar, text="Status:").grid(row=0, column=0, padx=(12, 6), pady=6, sticky="w")
        ctk.CTkLabel(status_bar, textvariable=self.status_var).grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")

    def _build_sync_tab(self, parent: Any) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(parent, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="Instagram URL").grid(row=0, column=0, padx=(16, 8), pady=14, sticky="w")
        self.url_entry = ctk.CTkEntry(header)
        self.url_entry.grid(row=0, column=1, padx=(0, 16), pady=14, sticky="ew")

        options = ctk.CTkFrame(parent, corner_radius=0)
        options.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 8))
        options.grid_columnconfigure(1, weight=1)
        options.grid_columnconfigure(3, weight=0)

        ctk.CTkLabel(options, text="模式").grid(row=0, column=0, padx=(0, 8), pady=8, sticky="w")
        self.mode = ctk.CTkSegmentedButton(options, values=[MODE_POST, MODE_AUTHOR])
        self.mode.grid(row=0, column=1, padx=(0, 16), pady=8, sticky="w")

        ctk.CTkLabel(options, text="Max posts").grid(row=0, column=2, padx=(0, 8), pady=8, sticky="e")
        self.max_posts_entry = ctk.CTkEntry(options, width=96)
        self.max_posts_entry.grid(row=0, column=3, pady=8, sticky="e")

        ctk.CTkLabel(options, text="Eagle folder path").grid(row=1, column=0, padx=(0, 8), pady=8, sticky="w")
        self.folder_path_entry = ctk.CTkEntry(options)
        self.folder_path_entry.grid(row=1, column=1, columnspan=3, pady=8, sticky="ew")

        toggles = ctk.CTkFrame(parent, corner_radius=0)
        toggles.grid(row=2, column=0, sticky="ew", padx=16, pady=8)
        for column in range(5):
            toggles.grid_columnconfigure(column, weight=1)

        self.verify_var = ctk.BooleanVar(value=True)
        self.ignore_archive_var = ctk.BooleanVar(value=False)
        self.force_var = ctk.BooleanVar(value=False)
        self.dry_run_var = ctk.BooleanVar(value=False)
        self.show_annotation_var = ctk.BooleanVar(value=False)

        ctk.CTkCheckBox(toggles, text="verify-eagle", variable=self.verify_var).grid(
            row=0, column=0, padx=4, pady=8, sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="ignore-archive", variable=self.ignore_archive_var).grid(
            row=0, column=1, padx=4, pady=8, sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="force", variable=self.force_var).grid(
            row=0, column=2, padx=4, pady=8, sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="dry-run", variable=self.dry_run_var).grid(
            row=0, column=3, padx=4, pady=8, sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="show-annotation", variable=self.show_annotation_var).grid(
            row=0, column=4, padx=4, pady=8, sticky="w"
        )

        log_tools = ctk.CTkFrame(parent, corner_radius=0)
        log_tools.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        log_tools.grid_columnconfigure(2, weight=1)
        self.clear_log_button = ctk.CTkButton(log_tools, text="清空日志", width=96, command=self.clear_log)
        self.clear_log_button.grid(row=0, column=0, padx=(0, 8), pady=6)
        self.copy_log_button = ctk.CTkButton(log_tools, text="复制日志", width=96, command=self.copy_log)
        self.copy_log_button.grid(row=0, column=1, padx=8, pady=6)

        self.log_text = ctk.CTkTextbox(parent, wrap="word")
        self.log_text.grid(row=4, column=0, sticky="nsew", padx=16, pady=(4, 12))

        actions = ctk.CTkFrame(parent, corner_radius=0)
        actions.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(7, weight=1)

        self.preview_button = ctk.CTkButton(actions, text="预览", command=self.preview)
        self.preview_button.grid(row=0, column=0, padx=(0, 8), pady=8)
        self.sync_button = ctk.CTkButton(actions, text="开始同步", command=self.start_sync)
        self.sync_button.grid(row=0, column=1, padx=8, pady=8)
        self.folder_button = ctk.CTkButton(actions, text="检查 Eagle 文件夹", command=self.ensure_folder)
        self.folder_button.grid(row=0, column=2, padx=8, pady=8)
        self.open_staging_button = ctk.CTkButton(actions, text="打开 staging 目录", command=self.open_staging_dir)
        self.open_staging_button.grid(row=0, column=3, padx=8, pady=8)
        self.open_config_button = ctk.CTkButton(actions, text="打开 config 目录", command=self.open_config_dir)
        self.open_config_button.grid(row=0, column=4, padx=8, pady=8)
        self.open_readme_button = ctk.CTkButton(actions, text="打开 README.md", command=self.open_readme)
        self.open_readme_button.grid(row=0, column=5, padx=8, pady=8)

    def _build_settings_tab(self, parent: Any) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkScrollableFrame(parent, corner_radius=0)
        panel.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        panel.grid_columnconfigure(1, weight=1)

        self._add_setting_row(panel, 0, "cookies.txt 路径", "cookies_file", "选择文件", self.choose_cookies_file)
        self._add_setting_row(panel, 1, "staging_dir", "staging_dir", "选择目录", self.choose_staging_dir)
        self._add_setting_row(panel, 2, "archive_db", "archive_db")
        self._add_setting_row(panel, 3, "imported_state", "imported_state")
        self._add_setting_row(panel, 4, "Eagle API base", "eagle_api_base")
        self._add_setting_row(panel, 5, "默认 Eagle folder path", "default_folder_path")
        self._add_setting_row(panel, 6, "HTTP proxy", "http_proxy")
        self._add_setting_row(panel, 7, "HTTPS proxy", "https_proxy")
        self._add_setting_row(panel, 8, "默认 max posts", "max_posts")
        self._add_setting_row(panel, 9, "默认 sleep request", "sleep_request")

        actions = ctk.CTkFrame(panel, corner_radius=0)
        actions.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(18, 6))
        actions.grid_columnconfigure(2, weight=1)
        self.save_settings_button = ctk.CTkButton(actions, text="保存设置", command=self.save_settings)
        self.save_settings_button.grid(row=0, column=0, padx=(0, 8), pady=8)
        self.reload_settings_button = ctk.CTkButton(actions, text="重新加载", command=self.reload_settings)
        self.reload_settings_button.grid(row=0, column=1, padx=8, pady=8)

    def _add_setting_row(
        self,
        parent: Any,
        row: int,
        label: str,
        key: str,
        button_text: str | None = None,
        button_command: Callable[[], None] | None = None,
    ) -> None:
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=(0, 10), pady=8, sticky="w")
        entry = ctk.CTkEntry(parent)
        entry.grid(row=row, column=1, pady=8, sticky="ew")
        self.setting_entries[key] = entry
        if button_text and button_command:
            button = ctk.CTkButton(parent, text=button_text, width=96, command=button_command)
            button.grid(row=row, column=2, padx=(10, 0), pady=8, sticky="e")

    def _set_default_values(self) -> None:
        self.mode.set(MODE_POST)
        self._set_entry(self.folder_path_entry, get_config_value(self.config_data, "default_folder_path"))
        self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
        self._populate_settings_form()

    def _load_config(self) -> AppConfig:
        try:
            return load_config(self.config_path)
        except Exception as exc:  # noqa: BLE001 - visible GUI error, then re-raise to prevent half-init.
            raise RuntimeError(f"Failed to load config from {self.config_path}: {exc}") from exc

    def _populate_settings_form(self) -> None:
        values = {
            "cookies_file": get_config_value(self.config_data, "cookies_file"),
            "staging_dir": get_config_value(self.config_data, "staging_dir"),
            "archive_db": get_config_value(self.config_data, "archive_db"),
            "imported_state": get_config_value(self.config_data, "imported_state"),
            "eagle_api_base": get_config_value(self.config_data, "eagle_api_base"),
            "default_folder_path": get_config_value(self.config_data, "default_folder_path"),
            "http_proxy": get_config_value(self.config_data, "http_proxy"),
            "https_proxy": get_config_value(self.config_data, "https_proxy"),
            "max_posts": str(get_config_value(self.config_data, "max_posts")),
            "sleep_request": get_config_value(self.config_data, "sleep_request"),
        }
        for key, value in values.items():
            self._set_entry(self.setting_entries[key], str(value or ""))

    def choose_cookies_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self._set_entry(self.setting_entries["cookies_file"], path)

    def choose_staging_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 staging 目录")
        if path:
            self._set_entry(self.setting_entries["staging_dir"], path)

    def save_settings(self) -> None:
        try:
            data = self._collect_settings_data()
            if data is None:
                return
            write_config_data(data, DEFAULT_CONFIG_PATH)
            self.config_path = Path(DEFAULT_CONFIG_PATH)
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            self._set_entry(self.folder_path_entry, get_config_value(self.config_data, "default_folder_path"))
            self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
            self._append_log("settings saved to config.json")
            self._warn_about_cookies()
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"error: failed to save settings: {exc}")

    def reload_settings(self) -> None:
        try:
            self.config_path = ensure_config_file(DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH)
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            self._set_entry(self.folder_path_entry, get_config_value(self.config_data, "default_folder_path"))
            self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
            self._append_log(f"settings reloaded from {self.config_path}")
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"error: failed to reload settings: {exc}")

    def _collect_settings_data(self) -> dict[str, Any] | None:
        eagle_api_base = self._setting_value("eagle_api_base")
        folder_path = self._setting_value("default_folder_path")
        max_posts_text = self._setting_value("max_posts")
        sleep_request = self._setting_value("sleep_request")

        if not eagle_api_base:
            self._append_log("error: Eagle API base is required.")
            return None
        if not folder_path:
            self._append_log("error: default Eagle folder path is required.")
            return None
        if not sleep_request:
            self._append_log("error: default sleep request is required.")
            return None
        try:
            max_posts = int(max_posts_text)
        except ValueError:
            self._append_log("error: default max posts must be an integer.")
            return None
        if max_posts <= 0:
            self._append_log("error: default max posts must be greater than 0.")
            return None

        data = normalize_config_data(self.config_data)
        cookies_file = self._setting_value("cookies_file")
        http_proxy = self._setting_value("http_proxy")
        https_proxy = self._setting_value("https_proxy")

        data["staging_dir"] = self._setting_value("staging_dir")
        data["archive_db"] = self._setting_value("archive_db")
        data["imported_state"] = self._setting_value("imported_state")
        data["eagle_api_base"] = eagle_api_base.rstrip("/")
        data["default_eagle_root_folder"] = folder_path
        data["cookies"]["enabled"] = bool(cookies_file)
        data["cookies"]["from_browser"] = ""
        data["cookies"]["file"] = cookies_file
        data["proxy"]["enabled"] = bool(http_proxy or https_proxy)
        data["proxy"]["http_proxy"] = http_proxy
        data["proxy"]["https_proxy"] = https_proxy
        data["download"]["max_posts"] = max_posts
        data["download"]["sleep_request"] = sleep_request
        return data

    def _setting_value(self, key: str) -> str:
        return self.setting_entries[key].get().strip()

    def startup_checks(self) -> None:
        def run() -> None:
            for message in run_startup_checks(self.config):
                self._queue_log(message)

        threading.Thread(target=run, daemon=True).start()

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def copy_log(self) -> None:
        try:
            text = self.log_text.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(text)
            self._append_log("log copied to clipboard.")
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"error: could not copy log: {exc}")

    def preview(self) -> None:
        self._run_sync_task(force_dry_run=True)

    def start_sync(self) -> None:
        self._run_sync_task(force_dry_run=False)

    def ensure_folder(self) -> None:
        folder_path = self.folder_path_entry.get().strip()
        if not folder_path:
            self._append_log("error: Eagle folder path is required.")
            return
        if not self.config.eagle_api_base:
            self._append_log("error: Eagle API base is required.")
            return

        def task() -> dict[str, Any]:
            return services.ensure_folder(self.config, folder_path)

        self._start_worker("检查 Eagle 文件夹", task)

    def open_staging_dir(self) -> None:
        try:
            path = self._target_staging_dir()
        except Exception as exc:  # noqa: BLE001 - user-facing log.
            self._append_log(f"error: {exc}")
            return

        if not path.exists():
            self._append_log(f"warning: staging directory does not exist: {path}")
            return

        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self._append_log(f"opened staging directory: {path}")
        except Exception as exc:  # noqa: BLE001 - user-facing log.
            self._append_log(f"error: could not open staging directory {path}: {exc}")

    def open_config_dir(self) -> None:
        self._open_path(Path(self.config_path).resolve().parent, "config directory")

    def open_readme(self) -> None:
        readme_path = Path("README.md").resolve()
        if not readme_path.exists():
            self._append_log(f"warning: README.md does not exist: {readme_path}")
            return
        self._open_path(readme_path, "README.md")

    def _open_path(self, path: Path, label: str) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self._append_log(f"opened {label}: {path}")
        except Exception as exc:  # noqa: BLE001 - user-facing log.
            self._append_log(f"error: could not open {label}: {exc}")

    def _run_sync_task(self, *, force_dry_run: bool) -> None:
        url = self.url_entry.get().strip()
        folder_path = self.folder_path_entry.get().strip()
        if not url:
            self._append_log("error: Instagram URL is required.")
            return
        if not folder_path:
            self._append_log("error: Eagle folder path is required.")
            return
        if not self.config.eagle_api_base:
            self._append_log("error: Eagle API base is required.")
            return

        max_posts = self._read_max_posts()
        if max_posts is False:
            return

        self._warn_about_cookies()
        dry_run = True if force_dry_run else self.dry_run_var.get()
        mode = self.mode.get()

        def task() -> dict[str, Any]:
            kwargs = {
                "folder_path": folder_path,
                "dry_run": dry_run,
                "force": self.force_var.get(),
                "verify_eagle": self.verify_var.get(),
                "show_annotation": self.show_annotation_var.get(),
                "ignore_archive": self.ignore_archive_var.get(),
                "log": self._queue_log,
            }
            if mode == MODE_AUTHOR:
                return services.sync_author(self.config, url, max_posts=max_posts, **kwargs)
            return services.sync_post(self.config, url, **kwargs)

        title = "预览" if force_dry_run else "同步"
        self._start_worker(title, task)

    def _read_max_posts(self) -> int | None | bool:
        raw = self.max_posts_entry.get().strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            self._append_log("error: max posts must be an integer.")
            return False
        if value <= 0:
            self._append_log("error: max posts must be greater than 0.")
            return False
        return value

    def _target_staging_dir(self) -> Path:
        url = self.url_entry.get().strip()
        if not url:
            return self.config.staging_dir

        info = detect_instagram_url(url)
        if self.mode.get() == MODE_AUTHOR:
            if info.mode != InstagramMode.AUTHOR or not info.username:
                raise ValueError("author mode requires an author URL.")
            return self.config.staging_dir / info.username

        if info.mode != InstagramMode.POST or not info.shortcode:
            raise ValueError("single-post mode requires a post or reel URL.")
        return self.config.staging_dir / "unknown" / info.shortcode

    def _warn_about_cookies(self) -> None:
        cookie_file = self.config.cookies.file
        if cookie_file is None:
            self._append_log("warning: cookies.txt path is empty. Instagram may require login cookies.")
            return
        if not cookie_file.exists():
            self._append_log("warning: cookies.txt file does not exist: <hidden>")

    def _start_worker(self, label: str, task: Callable[[], dict[str, Any]]) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._append_log("warning: another task is already running.")
            return

        self._set_controls_enabled(False)
        self._set_status(STATUS_RUNNING)
        self._append_log("")
        self._append_log(f"== {label} started ==")

        def run() -> None:
            done_message = "__TASK_DONE_FAILED__"
            try:
                result = task()
                done_message = "__TASK_DONE_OK__" if result.get("ok") else "__TASK_DONE_FAILED__"
                self._queue_log(f"== {label} finished: {'ok' if result.get('ok') else 'failed'} ==")
                self._queue_summary(result)
            except Exception:
                self._queue_log("error: unhandled exception")
                self._queue_log(traceback.format_exc())
            finally:
                self.log_queue.put(done_message)

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _queue_summary(self, result: dict[str, Any]) -> None:
        summary_keys = (
            "total",
            "skipped",
            "imported",
            "failed",
            "checked",
            "alive",
            "missing",
            "alive_but_not_in_folder",
            "unknown",
            "removed",
            "folder_id",
            "returncode",
        )
        for key in summary_keys:
            if key in result:
                self._queue_log(f"{key}: {result[key]}")

    def _queue_log(self, message: object) -> None:
        self.log_queue.put(self._sanitize_log_message(message))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if message == "__TASK_DONE_OK__":
                self._set_controls_enabled(True)
                self._set_status(STATUS_DONE)
            elif message == "__TASK_DONE_FAILED__":
                self._set_controls_enabled(True)
                self._set_status(STATUS_FAILED)
            else:
                self._append_log(message)

        self.after(100, self._drain_log_queue)

    def _append_log(self, message: object) -> None:
        self.log_text.insert("end", self._sanitize_log_message(message) + "\n")
        self.log_text.see("end")

    def _sanitize_log_message(self, message: object) -> str:
        return sanitize_log_message(message, config_data=self.config_data, config=self.config)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (
            self.preview_button,
            self.sync_button,
            self.folder_button,
            self.open_staging_button,
            self.open_config_button,
            self.open_readme_button,
            self.clear_log_button,
            self.copy_log_button,
            self.save_settings_button,
            self.reload_settings_button,
        ):
            button.configure(state=state)
        if enabled:
            self.sync_button.configure(text="开始同步")
        else:
            self.sync_button.configure(text="正在运行...")

    def _set_status(self, value: str) -> None:
        self.status_var.set(value)

    @staticmethod
    def _set_entry(entry: Any, value: object) -> None:
        entry.delete(0, "end")
        entry.insert(0, str(value))


def ensure_config_file(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    example_path: str | Path = EXAMPLE_CONFIG_PATH,
) -> Path:
    path = Path(config_path)
    if path.exists():
        return path

    example = Path(example_path)
    if example.exists():
        data = load_config_data(example)
    else:
        data = default_config_data()
    write_config_data(data, path)
    return path


def load_config_data(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    return normalize_config_data(data)


def write_config_data(data: dict[str, Any], path: str | Path) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_config_data(data)
    config_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_config_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = default_config_data()
    _deep_update(normalized, data)
    return normalized


def default_config_data() -> dict[str, Any]:
    return deepcopy(DEFAULT_CONFIG_DATA)


def get_config_value(data: dict[str, Any], key: str) -> Any:
    if key == "cookies_file":
        return data.get("cookies", {}).get("file") or ""
    if key == "staging_dir":
        return data.get("staging_dir", "")
    if key == "archive_db":
        return data.get("archive_db", "")
    if key == "imported_state":
        return data.get("imported_state", "")
    if key == "eagle_api_base":
        return data.get("eagle_api_base", "")
    if key == "default_folder_path":
        return data.get("default_eagle_root_folder") or DEFAULT_FOLDER_PATH
    if key == "http_proxy":
        return data.get("proxy", {}).get("http_proxy") or ""
    if key == "https_proxy":
        return data.get("proxy", {}).get("https_proxy") or ""
    if key == "max_posts":
        return data.get("download", {}).get("max_posts", 50)
    if key == "sleep_request":
        return data.get("download", {}).get("sleep_request", "8-15")
    raise KeyError(key)


def sanitize_log_message(
    message: object,
    *,
    config_data: dict[str, Any] | None = None,
    config: AppConfig | None = None,
) -> str:
    text = str(message)
    for secret in _cookie_path_candidates(config_data=config_data, config=config):
        if secret:
            text = text.replace(secret, "<hidden>")
    return text


def run_startup_checks(config: AppConfig) -> list[str]:
    messages = ["startup checks:"]

    if config.eagle_api_base:
        try:
            EagleClient(config.eagle_api_base).check_app_available()
            messages.append("ok: Eagle API is reachable.")
        except Exception as exc:  # noqa: BLE001 - startup diagnostics should never crash GUI.
            messages.append(f"warning: Eagle API is not reachable: {exc}")
    else:
        messages.append("warning: Eagle API base is empty.")

    cookie_file = config.cookies.file
    if cookie_file is None:
        messages.append("warning: cookies.txt path is empty. Instagram may require login cookies.")
    elif cookie_file.exists():
        messages.append("ok: cookies.txt exists: <hidden>")
    else:
        messages.append("warning: cookies.txt file does not exist: <hidden>")

    gallery_ok, gallery_message = check_gallery_dl_available(config.gallery_dl_executable)
    messages.append(gallery_message if gallery_ok else f"warning: {gallery_message}")
    return [sanitize_log_message(message, config=config) for message in messages]


def check_gallery_dl_available(gallery_dl_executable: str) -> tuple[bool, str]:
    command = [*shlex.split(gallery_dl_executable), "--version"]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 - startup diagnostics should stay non-fatal.
        return False, f"gallery-dl is not available: {exc}"

    if result.returncode == 0:
        version = (result.stdout or result.stderr or "").strip()
        suffix = f" ({version})" if version else ""
        return True, f"ok: gallery-dl is available{suffix}."
    stderr = (result.stderr or result.stdout or "").strip()
    detail = f": {stderr}" if stderr else ""
    return False, f"gallery-dl check failed with exit code {result.returncode}{detail}"


def resolve_config_path(config_path: str) -> Path:
    path = Path(config_path)
    if path.exists():
        return path

    if config_path == DEFAULT_CONFIG_PATH:
        example_path = Path(EXAMPLE_CONFIG_PATH)
        if example_path.exists():
            return example_path

    return path


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _cookie_path_candidates(
    *,
    config_data: dict[str, Any] | None,
    config: AppConfig | None,
) -> set[str]:
    candidates: set[str] = set()
    if config_data:
        raw = config_data.get("cookies", {}).get("file")
        if raw:
            candidates.update(_path_variants(str(raw)))
    if config and config.cookies.file:
        candidates.update(_path_variants(str(config.cookies.file)))
    return candidates


def _path_variants(path_text: str) -> set[str]:
    path = Path(path_text)
    return {
        path_text,
        str(path),
        path.as_posix(),
        path_text.replace("/", "\\"),
        path_text.replace("\\", "/"),
    }


def main() -> None:
    if ctk is None:
        raise SystemExit("customtkinter is not installed. Run: py -m pip install customtkinter")

    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = InsEagleSyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
