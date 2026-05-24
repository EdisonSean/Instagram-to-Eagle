from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency hint for GUI users.
    ctk = None  # type: ignore[assignment]

from . import services
from .config import AppConfig, load_config
from .utils import InstagramMode, detect_instagram_url


DEFAULT_CONFIG_PATH = "config.json"
EXAMPLE_CONFIG_PATH = "config.example.json"
MODE_POST = "单帖 sync-post"
MODE_AUTHOR = "作者 sync-author"
_BaseWindow = ctk.CTk if ctk is not None else object


class InsEagleSyncApp(_BaseWindow):
    def __init__(self) -> None:
        super().__init__()
        self.title("ins-eagle-sync")
        self.geometry("980x720")
        self.minsize(860, 620)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.config_path = resolve_config_path(DEFAULT_CONFIG_PATH)
        self.config = self._load_config()

        self._build_layout()
        self._set_default_values()
        self.after(100, self._drain_log_queue)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="Instagram URL").grid(row=0, column=0, padx=(16, 8), pady=14, sticky="w")
        self.url_entry = ctk.CTkEntry(header)
        self.url_entry.grid(row=0, column=1, padx=(0, 16), pady=14, sticky="ew")

        options = ctk.CTkFrame(self, corner_radius=0)
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

        toggles = ctk.CTkFrame(self, corner_radius=0)
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

        self.log_text = ctk.CTkTextbox(self, wrap="word")
        self.log_text.grid(row=3, column=0, sticky="nsew", padx=16, pady=(8, 12))

        actions = ctk.CTkFrame(self, corner_radius=0)
        actions.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(4, weight=1)

        self.preview_button = ctk.CTkButton(actions, text="预览", command=self.preview)
        self.preview_button.grid(row=0, column=0, padx=(0, 8), pady=8)
        self.sync_button = ctk.CTkButton(actions, text="开始同步", command=self.start_sync)
        self.sync_button.grid(row=0, column=1, padx=8, pady=8)
        self.folder_button = ctk.CTkButton(actions, text="检查 Eagle 文件夹", command=self.ensure_folder)
        self.folder_button.grid(row=0, column=2, padx=8, pady=8)
        self.open_staging_button = ctk.CTkButton(actions, text="打开 staging 目录", command=self.open_staging_dir)
        self.open_staging_button.grid(row=0, column=3, padx=8, pady=8)

    def _set_default_values(self) -> None:
        self.mode.set(MODE_POST)
        self.folder_path_entry.insert(0, "Instagram/quinn.xyz")
        self.max_posts_entry.insert(0, str(self.config.download.max_posts))

    def _load_config(self) -> AppConfig:
        try:
            return load_config(self.config_path)
        except Exception as exc:  # noqa: BLE001 - visible GUI error, then re-raise to prevent half-init.
            raise RuntimeError(f"Failed to load config from {self.config_path}: {exc}") from exc

    def preview(self) -> None:
        self._run_sync_task(force_dry_run=True)

    def start_sync(self) -> None:
        self._run_sync_task(force_dry_run=False)

    def ensure_folder(self) -> None:
        folder_path = self.folder_path_entry.get().strip()
        if not folder_path:
            self._append_log("error: Eagle folder path is required.")
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

    def _run_sync_task(self, *, force_dry_run: bool) -> None:
        url = self.url_entry.get().strip()
        folder_path = self.folder_path_entry.get().strip()
        if not url:
            self._append_log("error: Instagram URL is required.")
            return
        if not folder_path:
            self._append_log("error: Eagle folder path is required.")
            return

        max_posts = self._read_max_posts()
        if max_posts is False:
            return

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

    def _start_worker(self, label: str, task: Callable[[], dict[str, Any]]) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._append_log("warning: another task is already running.")
            return

        self._set_controls_enabled(False)
        self._append_log("")
        self._append_log(f"== {label} started ==")

        def run() -> None:
            try:
                result = task()
                self._queue_log(f"== {label} finished: {'ok' if result.get('ok') else 'failed'} ==")
                self._queue_summary(result)
            except Exception:
                self._queue_log("error: unhandled exception")
                self._queue_log(traceback.format_exc())
            finally:
                self.log_queue.put("__TASK_DONE__")

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
        self.log_queue.put(str(message))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if message == "__TASK_DONE__":
                self._set_controls_enabled(True)
            else:
                self._append_log(message)

        self.after(100, self._drain_log_queue)

    def _append_log(self, message: object) -> None:
        self.log_text.insert("end", str(message) + "\n")
        self.log_text.see("end")

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (
            self.preview_button,
            self.sync_button,
            self.folder_button,
            self.open_staging_button,
        ):
            button.configure(state=state)


def resolve_config_path(config_path: str) -> Path:
    path = Path(config_path)
    if path.exists():
        return path

    if config_path == DEFAULT_CONFIG_PATH:
        example_path = Path(EXAMPLE_CONFIG_PATH)
        if example_path.exists():
            return example_path

    return path


def main() -> None:
    if ctk is None:
        raise SystemExit("customtkinter is not installed. Run: py -m pip install customtkinter")

    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = InsEagleSyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
