from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import traceback
import tkinter as tk
import webbrowser
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency hint for GUI users.
    ctk = None  # type: ignore[assignment]

from . import services
from .config import (
    FROZEN_GALLERY_DL_MODULE_ARG,
    GALLERY_DL_EXE_NAME,
    YT_DLP_EXE_NAME,
    AppConfig,
    load_config,
    parse_config,
    resolve_gallery_dl_command,
    resolve_ytdlp_command,
    split_command,
)
from .eagle_client import EagleClient
from .gallerydl_runner import build_cookie_args, build_subprocess_env, format_command_for_log, is_browser_cookie_error
from .proxy_utils import detect_system_proxy, normalize_proxy_url, proxy_mode_label
from .runtime import (
    APP_ICON_RELATIVE_PATH,
    get_resource_path,
    get_runtime_config_path,
    get_runtime_example_config_path,
    get_runtime_readme_path,
    is_frozen,
)
from .ui_theme import (
    APP_TITLE,
    BUTTON_HEIGHT,
    BUTTON_STYLES,
    CHECKBOX_STYLE,
    COLORS,
    COMBOBOX_STYLE,
    ENTRY_STYLE,
    FONTS,
    INPUT_HEIGHT,
    RADIUS,
    SCROLLBAR_STYLE,
    SEGMENTED_STYLE,
    SPACE,
    TEXTBOX_STYLE,
)
from .utils import InstagramMode, detect_instagram_url


DEFAULT_CONFIG_PATH = "config.json"
EXAMPLE_CONFIG_PATH = "config.example.json"
MODE_POST = "单个帖子"
MODE_AUTHOR = "作者主页"
SYNC_TAB_NAME = "同步"
SETTINGS_TAB_NAME = "设置"
DEFAULT_FOLDER_PATH = "Instagram/quinn.xyz"
STORAGE_PARENT_KEY = "storage_parent_dir"
STAGING_DIR_NAME = "_staging"
CACHE_DIR_NAME = "_cache"
ARCHIVE_DB_NAME = "gallery-dl-archive.sqlite3"
IMPORTED_STATE_NAME = "eagle-imported.json"
DEFAULT_LOGIN_TEST_URL = "https://www.instagram.com/instagram/"
LOGIN_COOKIE_FILE = "使用 cookies.txt 文件（推荐，稳定）"
LOGIN_BROWSER = "自动从浏览器读取登录状态（实验性）"
LOGIN_NONE = "不登录，仅下载公开内容"
PROXY_AUTO = "自动检测系统代理（推荐）"
PROXY_MANUAL = "手动设置代理"
PROXY_NONE = "不使用代理"
PROXY_MODE_VALUES = (PROXY_AUTO, PROXY_MANUAL, PROXY_NONE)
PROXY_MODE_TO_VALUE = {PROXY_AUTO: "auto", PROXY_MANUAL: "manual", PROXY_NONE: "none"}
PROXY_VALUE_TO_MODE = {"auto": PROXY_AUTO, "manual": PROXY_MANUAL, "none": PROXY_NONE}
DATE_RANGE_DAY = "天"
DATE_RANGE_WEEK = "周"
DATE_RANGE_MONTH = "月"
DATE_RANGE_YEAR = "年"
DATE_RANGE_VALUES = (DATE_RANGE_DAY, DATE_RANGE_WEEK, DATE_RANGE_MONTH, DATE_RANGE_YEAR)
AUTHOR_SYNC_UNLIMITED = "不限制数量"
AUTHOR_SYNC_RECENT = "最近 N 条"
AUTHOR_SYNC_DATE_RANGE = "按时间范围"
AUTHOR_SYNC_RANGE_VALUES = (AUTHOR_SYNC_UNLIMITED, AUTHOR_SYNC_RECENT, AUTHOR_SYNC_DATE_RANGE)
BROWSER_LABELS = ("Chrome", "Edge", "Firefox")
BROWSER_VALUES = {"Chrome": "chrome", "Edge": "edge", "Firefox": "firefox"}
COOKIE_HELP_URL = "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
FRIENDLY_LOGIN_FAILURE_HINT = (
    "浏览器登录状态读取失败。可能原因是浏览器 Cookie 加密、Profile 选择错误，"
    "或浏览器仍在运行。请尝试关闭浏览器后重试；如果仍失败，建议改用 cookies.txt 文件方式。"
)
STATUS_READY = "就绪"
STATUS_RUNNING = "运行中"
STATUS_DONE = "完成"
STATUS_FAILED = "失败"
LOG_PANEL_TITLE = "运行日志"
SHOW_BROWSER_COOKIE_HELP = "__SHOW_BROWSER_COOKIE_HELP__"
FOLDER_DISPLAY_ICON = ""
FOLDER_ROW_HEIGHT = 34
FOLDER_INDENT = 24
FOLDER_ARROW_WIDTH = 34
LOG_FLUSH_INTERVAL_MS = 75
MAX_LOG_LINES = 5000
LOG_BATCH_LIMIT = 300
FOLDER_SEARCH_DEBOUNCE_MS = 200
TREE_RENDER_BUFFER_ROWS = 4
MAIN_SCROLL_UNITS_PER_WHEEL = 75
SETTINGS_SCROLL_TOP_PADDING = 36
RESIZE_IDLE_DEBOUNCE_MS = 220
LOG_FLUSH_RESIZE_DELAY_MS = 180
LOG_PANEL_WIDTH = 430
SETTINGS_SECTION_FLASH_STEPS = (
    (0, "primary_soft"),
    (120, "primary"),
    (260, "primary_hover"),
    (430, "primary"),
    (620, "primary_soft"),
)

DEFAULT_CONFIG_DATA: dict[str, Any] = {
    "gallery_dl_executable": "py -m gallery_dl",
    "yt_dlp_executable": "",
    STORAGE_PARENT_KEY: "",
    "staging_dir": "E:/INS_Eagle_Sync/_staging",
    "archive_db": "E:/INS_Eagle_Sync/_cache/gallery-dl-archive.sqlite3",
    "imported_state": "E:/INS_Eagle_Sync/_cache/eagle-imported.json",
    "eagle_api_base": "http://localhost:41595",
    "default_eagle_root_folder": DEFAULT_FOLDER_PATH,
    "default_eagle_folder_path": DEFAULT_FOLDER_PATH,
    "default_eagle_folder_id": "",
    "last_eagle_folder_path": "",
    "last_eagle_folder_id": "",
    "title_caption_chars": 70,
    "proxy": {
        "mode": "auto",
        "http_proxy": "",
        "https_proxy": "",
        "detected_proxy": "",
    },
    "cookies": {
        "enabled": False,
        "from_browser": "",
        "file": "E:/INS_Eagle_Sync/_cache/instagram-cookies.txt",
    },
    "download": {
        "sleep_request": "8-15",
        "max_posts": -1,
    },
}

_BaseWindow = ctk.CTk if ctk is not None else object


def center_window(window: Any, width: int, height: int) -> None:
    try:
        window.update_idletasks()
        screen_width = int(window.winfo_screenwidth())
        screen_height = int(window.winfo_screenheight())
    except Exception:  # noqa: BLE001 - fallback keeps the requested size.
        window.geometry(f"{width}x{height}")
        return

    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def show_centered_info(parent: Any, title: str, message: str) -> None:
    show_centered_message(parent, "info", title, message)


def show_centered_warning(parent: Any, title: str, message: str) -> None:
    show_centered_message(parent, "warning", title, message)


def show_centered_message(parent: Any, kind: str, title: str, message: str) -> None:
    host = None
    try:
        host = tk.Toplevel(parent)
        host.withdraw()
        host.title(title)
        center_window(host, 1, 1)
        host.transient(parent)
        try:
            host.attributes("-alpha", 0.0)
        except Exception:  # noqa: BLE001 - alpha is not guaranteed for all Tk builds.
            pass
        host.deiconify()
        host.lift()
        options = {"title": title, "message": message, "parent": host}
        if kind == "warning":
            messagebox.showwarning(**options)
        else:
            messagebox.showinfo(**options)
    finally:
        if host is not None:
            try:
                host.destroy()
            except Exception:  # noqa: BLE001 - best-effort cleanup for UI helpers.
                pass


class InsEagleSyncApp(_BaseWindow):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1500x900")
        self.minsize(1440, 800)
        self.configure(fg_color=COLORS["window"])
        self.icon_status_message: str | None = None
        self._set_window_icon()

        self.log_queue: queue.Queue[object] = queue.Queue()
        self.log_line_count = 0
        self.log_panel_visible = True
        self._is_resizing = False
        self._resize_after_id: str | None = None
        self._resize_debug_enabled = os.environ.get("INS_EAGLE_SYNC_RESIZE_DEBUG") == "1"
        self.resize_debug_stats = {
            "root_configure_events": 0,
            "log_flush_deferred": 0,
        }
        self.worker: threading.Thread | None = None
        self.browser_cookie_help_prompted = False
        self.setting_entries: dict[str, Any] = {}
        self.status_var = ctk.StringVar(value=STATUS_READY)
        self.proxy_detect_result_var = ctk.StringVar(value="当前检测结果：未检测")
        self.date_range_var = ctk.StringVar(value=DATE_RANGE_DAY)
        self.author_sync_range_var = ctk.StringVar(value=AUTHOR_SYNC_UNLIMITED)
        self.selected_folder_id: str | None = None
        self.selected_default_folder_id: str | None = None
        self.storage_preview_vars = {
            "staging_dir": ctk.StringVar(value="未设置"),
            "archive_db": ctk.StringVar(value="未设置"),
            "imported_state": ctk.StringVar(value="未设置"),
        }
        try:
            self.config_path = ensure_config_file(get_runtime_config_path(), get_runtime_example_config_path())
        except Exception as exc:  # noqa: BLE001 - startup must explain configuration write failures.
            show_centered_warning(self, "配置文件不可用", str(exc))
            raise
        self.config_data = load_config_data(self.config_path)
        self.config = self._load_config()

        self._build_layout()
        self._set_default_values()
        self.bind("<Configure>", self._on_root_configure, add="+")
        self.after(LOG_FLUSH_INTERVAL_MS, self._drain_log_queue)
        self.after(250, self.startup_checks)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0, minsize=LOG_PANEL_WIDTH)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.main_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.main_panel.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=(0, 10))
        self.main_panel.grid_columnconfigure(0, weight=1)
        self.main_panel.grid_rowconfigure(0, weight=1)

        self.sync_tab = ctk.CTkScrollableFrame(
            self.main_panel,
            fg_color=COLORS["surface"],
            corner_radius=RADIUS["card"],
            **SCROLLBAR_STYLE,
        )
        self.settings_tab = ctk.CTkFrame(
            self.main_panel,
            fg_color=COLORS["surface"],
            corner_radius=RADIUS["card"],
        )
        for frame in (self.sync_tab, self.settings_tab):
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)

        self._build_sync_tab(self.sync_tab)
        self._build_settings_tab(self.settings_tab)
        self._bind_scrollable_frame_mousewheel(self.sync_tab)
        self._show_main_tab(SYNC_TAB_NAME)
        self._build_log_panel()
        self._build_status_bar()

    def _set_window_icon(self) -> None:
        icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if not icon_path.exists():
            self.icon_status_message = "提示：未找到应用图标 assets/app_icon.ico。"
            return
        try:
            self.iconbitmap(str(icon_path))
        except Exception as exc:  # noqa: BLE001 - missing/invalid icons should not block GUI startup.
            self.icon_status_message = f"提示：应用图标加载失败：{exc}"
        else:
            self.icon_status_message = None

    def _build_status_bar(self) -> None:
        status_bar = ctk.CTkFrame(self, corner_radius=0)
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        status_bar.grid_columnconfigure(2, weight=1)
        status_bar.configure(fg_color=COLORS["surface"], border_width=1, border_color=COLORS["border_soft"])
        ctk.CTkLabel(status_bar, text="状态：", text_color=COLORS["text_muted"], font=FONTS["body"]).grid(
            row=0, column=0, padx=(12, 4), pady=6, sticky="w"
        )
        ctk.CTkLabel(status_bar, textvariable=self.status_var, text_color=COLORS["text"], font=FONTS["body"]).grid(
            row=0, column=1, padx=(0, 10), pady=6, sticky="w"
        )
        self.status_dot = ctk.CTkLabel(status_bar, text="●", text_color=COLORS["success"], font=(FONTS["body"][0], 12))
        self.status_dot.grid(row=0, column=2, padx=(0, 12), pady=6, sticky="w")
        self.toggle_log_button = self._button(status_bar, "隐藏日志", self.toggle_log_panel, kind="ghost", width=96, height=26)
        self.toggle_log_button.grid(row=0, column=3, padx=10, pady=4, sticky="e")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self,
            fg_color=COLORS["window"],
            corner_radius=0,
            height=52,
            border_width=1,
            border_color=COLORS["border_soft"],
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=1)

        self.nav_tabs = ctk.CTkSegmentedButton(
            header,
            values=[SYNC_TAB_NAME, SETTINGS_TAB_NAME],
            command=self._show_main_tab,
            width=280,
            height=36,
            corner_radius=RADIUS["pill"],
            **{**SEGMENTED_STYLE, "font": (FONTS["button"][0], 14, "bold")},
        )
        self.nav_tabs.grid(row=0, column=1, pady=10)
        self.nav_tabs.set(SYNC_TAB_NAME)

    def _bind_scrollable_frame_mousewheel(self, frame: Any) -> None:
        canvas = getattr(frame, "_parent_canvas", None)
        if canvas is None:
            return

        def scroll(event: object) -> str:
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(int(-1 * (delta / 120)) * MAIN_SCROLL_UNITS_PER_WHEEL, "units")
                if frame is self.__dict__.get("settings_content_scroll") or frame is self.__dict__.get("settings_tab"):
                    self._schedule_settings_nav_update()
            return "break"

        self._bind_mousewheel_to_widget(frame, scroll)
        self._bind_mousewheel_to_widget(canvas, scroll)
        self._bind_mousewheel_to_children(frame, scroll)

    def _bind_mousewheel_to_widget(self, widget: Any, callback: Callable[[object], str]) -> None:
        try:
            widget.bind("<MouseWheel>", callback)
        except Exception:  # noqa: BLE001 - CustomTkinter internals can vary.
            return

    def _bind_mousewheel_to_children(self, widget: Any, callback: Callable[[object], str]) -> None:
        try:
            children = widget.winfo_children()
        except Exception:  # noqa: BLE001 - test doubles or alternate widgets may not expose children.
            return
        for child in children:
            self._bind_mousewheel_to_widget(child, callback)
            self._bind_mousewheel_to_children(child, callback)

    def _show_main_tab(self, value: str) -> None:
        if value == SETTINGS_TAB_NAME:
            self.sync_tab.grid_remove()
            self.settings_tab.grid()
            self._schedule_settings_nav_update()
        else:
            self.settings_tab.grid_remove()
            self.sync_tab.grid()

    def _on_root_configure(self, event: object) -> None:
        if getattr(event, "widget", None) is not self:
            return
        if self._resize_debug_enabled:
            self.resize_debug_stats["root_configure_events"] += 1
        self._is_resizing = True
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:  # noqa: BLE001 - resize debounce is best effort.
                pass
        self._resize_after_id = self.after(RESIZE_IDLE_DEBOUNCE_MS, self._finish_resize)

    def _finish_resize(self) -> None:
        self._resize_after_id = None
        self._is_resizing = False
        self._schedule_settings_nav_update()

    def _button(
        self,
        parent: Any,
        text: str,
        command: Callable[[], None],
        *,
        kind: str = "secondary",
        width: int = 120,
        height: int = BUTTON_HEIGHT,
    ) -> Any:
        style = BUTTON_STYLES.get(kind, BUTTON_STYLES["secondary"])
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            font=FONTS["button"],
            corner_radius=RADIUS["control"],
            **style,
        )

    def _card(self, parent: Any, row: int, title: str, icon: str, *, columns: int = 1) -> Any:
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["card"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=RADIUS["card"],
        )
        card.grid(row=row, column=0, sticky="ew", padx=SPACE["md"], pady=(0, SPACE["md"]))
        for column in range(columns):
            card.grid_columnconfigure(column, weight=1)
        ctk.CTkLabel(card, text=icon, text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=0, padx=(SPACE["md"], 6), pady=(SPACE["md"], SPACE["sm"]), sticky="w"
        )
        ctk.CTkLabel(card, text=title, text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=0, padx=(36, SPACE["md"]), pady=(SPACE["md"], SPACE["sm"]), sticky="w"
        )
        return card

    def _entry(self, parent: Any, *, placeholder: str = "", width: int | None = None) -> Any:
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            height=INPUT_HEIGHT,
            width=width or 120,
            **ENTRY_STYLE,
        )

    def _checkbox(self, parent: Any, text: str, variable: Any) -> Any:
        return ctk.CTkCheckBox(parent, text=text, variable=variable, **CHECKBOX_STYLE)

    def _configure_log_tags(self) -> None:
        try:
            self.log_text.tag_config("ok", foreground=COLORS["success"])
            self.log_text.tag_config("warning", foreground=COLORS["warning"])
            self.log_text.tag_config("error", foreground=COLORS["danger"])
            self.log_text.tag_config("muted", foreground=COLORS["text_muted"])
        except Exception:  # noqa: BLE001 - CTkTextbox implementations can vary.
            return

    def _build_log_panel(self) -> None:
        self.log_panel = ctk.CTkFrame(
            self,
            width=LOG_PANEL_WIDTH,
            corner_radius=RADIUS["card"],
            fg_color=COLORS["card"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.log_panel.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=(0, 10))
        self.log_panel.grid_columnconfigure(0, weight=1)
        self.log_panel.grid_rowconfigure(1, weight=1)

        log_tools = ctk.CTkFrame(self.log_panel, corner_radius=0, fg_color="transparent")
        log_tools.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        log_tools.grid_columnconfigure(5, weight=1)
        ctk.CTkLabel(log_tools, text="▤", text_color=COLORS["text_muted"], font=FONTS["section"]).grid(
            row=0, column=0, padx=(0, 8), pady=4, sticky="w"
        )
        ctk.CTkLabel(log_tools, text=LOG_PANEL_TITLE, text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=1, padx=(0, 12), pady=4, sticky="w"
        )
        self.clear_log_button = self._button(log_tools, "清空", self.clear_log, kind="ghost", width=58, height=26)
        self.clear_log_button.grid(row=0, column=2, padx=3, pady=4)
        self.copy_log_button = self._button(log_tools, "复制", self.copy_log, kind="ghost", width=58, height=26)
        self.copy_log_button.grid(row=0, column=3, padx=3, pady=4)
        self.close_log_button = self._button(log_tools, "关闭", self.toggle_log_panel, kind="ghost", width=58, height=26)
        self.close_log_button.grid(row=0, column=4, padx=3, pady=4)

        self.log_text = ctk.CTkTextbox(
            self.log_panel,
            wrap="word",
            width=LOG_PANEL_WIDTH - 26,
            border_width=1,
            **TEXTBOX_STYLE,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._configure_log_tags()
        self._bind_local_mousewheel(self.log_text)

    def _bind_local_mousewheel(self, widget: Any) -> None:
        def scroll(event: object) -> str:
            delta = getattr(event, "delta", 0)
            if delta:
                widget.yview_scroll(int(-1 * (delta / 120)), "units")
            return "break"

        try:
            widget.bind("<MouseWheel>", scroll)
        except Exception:  # noqa: BLE001 - alternate widgets may not support bind.
            return

    def _build_sync_tab(self, parent: Any) -> None:
        if getattr(self, "_sync_tab_built", False):
            return
        self._sync_tab_built = True
        parent.grid_columnconfigure(0, weight=1)

        source = self._card(parent, 1, "1. 来源", "⌁", columns=4)
        source.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(source, text="Instagram 链接", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=1, column=0, columnspan=4, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        self.url_entry = self._entry(source, placeholder="粘贴 Instagram 帖子链接、Reels 链接或作者主页链接…")
        self.url_entry.grid(row=2, column=0, columnspan=4, padx=SPACE["lg"], pady=(0, SPACE["md"]), sticky="ew")

        ctk.CTkLabel(source, text="同步类型", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=3, column=0, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="w"
        )
        self.mode = ctk.CTkSegmentedButton(
            source,
            values=[MODE_POST, MODE_AUTHOR],
            command=self._sync_mode_changed,
            height=30,
            **SEGMENTED_STYLE,
        )
        self.mode.grid(row=3, column=1, padx=(0, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="ew")

        self.author_options_slot = ctk.CTkFrame(source, fg_color="transparent", height=158)
        self.author_options_slot.grid(row=4, column=0, columnspan=4, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="ew")
        self.author_options_slot.grid_columnconfigure(0, weight=1)
        try:
            self.author_options_slot.grid_propagate(False)
        except Exception:  # noqa: BLE001 - test doubles may not implement propagation controls.
            pass

        self.author_options_panel = ctk.CTkFrame(
            self.author_options_slot,
            fg_color=COLORS["surface_3"],
            corner_radius=RADIUS["control"],
            border_width=1,
            border_color=COLORS["border_soft"],
        )
        self.author_options_panel.grid(row=0, column=0, sticky="ew")
        self.author_options_panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.author_options_panel,
            text="作者同步范围",
            text_color=COLORS["text"],
            font=FONTS["label"],
        ).grid(row=0, column=0, padx=SPACE["md"], pady=(SPACE["md"], SPACE["sm"]), sticky="w")
        self.author_range_choice = ctk.CTkSegmentedButton(
            self.author_options_panel,
            values=list(AUTHOR_SYNC_RANGE_VALUES),
            variable=self.author_sync_range_var,
            command=self._author_range_changed,
            height=30,
            **SEGMENTED_STYLE,
        )
        self.author_range_choice.grid(row=0, column=1, padx=SPACE["md"], pady=(SPACE["md"], SPACE["sm"]), sticky="ew")
        self.author_range_choice.set(AUTHOR_SYNC_UNLIMITED)

        self.recent_posts_frame = ctk.CTkFrame(self.author_options_panel, fg_color="transparent")
        self.recent_posts_frame.grid(row=1, column=0, columnspan=2, padx=SPACE["md"], pady=(0, SPACE["md"]), sticky="ew")
        self.recent_posts_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.recent_posts_frame,
            text="最多同步帖子数",
            text_color=COLORS["text"],
            font=FONTS["label"],
        ).grid(row=0, column=0, padx=(0, SPACE["sm"]), sticky="w")
        self.max_posts_entry = self._entry(self.recent_posts_frame, width=112)
        self.max_posts_entry.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            self.recent_posts_frame,
            text="仅在“最近 N 条”模式下生效。",
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.date_options_frame = ctk.CTkFrame(self.author_options_panel, fg_color="transparent")
        self.date_options_frame.grid(row=2, column=0, columnspan=2, padx=SPACE["md"], pady=(0, SPACE["md"]), sticky="ew")
        self.date_options_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.date_options_frame,
            text="开始日期",
            text_color=COLORS["text"],
            font=FONTS["label"],
        ).grid(row=0, column=0, padx=(0, SPACE["sm"]), pady=0, sticky="w")
        self.anchor_date_entry = self._entry(self.date_options_frame, placeholder="YYYY-MM-DD", width=112)
        self.anchor_date_entry.grid(row=0, column=1, pady=0, sticky="w")
        ctk.CTkLabel(
            self.date_options_frame,
            text="范围",
            text_color=COLORS["text"],
            font=FONTS["label"],
        ).grid(row=1, column=0, padx=(0, SPACE["sm"]), pady=(SPACE["xs"], 0), sticky="w")
        self.date_range_frame = ctk.CTkFrame(self.date_options_frame, fg_color="transparent")
        self.date_range_frame.grid(row=1, column=1, pady=(SPACE["xs"], 0), sticky="w")
        self.date_range_amount_entry = self._entry(self.date_range_frame, width=52)
        self.date_range_amount_entry.grid(row=0, column=0, padx=(0, SPACE["xs"]), sticky="e")
        self.date_range_choice = ctk.CTkSegmentedButton(
            self.date_range_frame,
            values=list(DATE_RANGE_VALUES),
            variable=self.date_range_var,
            height=28,
            **SEGMENTED_STYLE,
        )
        self.date_range_choice.grid(row=0, column=1, sticky="e")
        self._set_entry(self.date_range_amount_entry, "1")
        self.date_range_choice.set(DATE_RANGE_DAY)

        destination = self._card(parent, 2, "2. 导入位置", "▱", columns=3)
        destination.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(destination, text="Eagle 导入位置", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="w"
        )
        self.folder_path_entry = self._entry(destination, placeholder="例如：Instagram/quinn.xyz")
        self.folder_path_entry.grid(row=1, column=1, padx=(0, SPACE["sm"]), pady=(0, SPACE["lg"]), sticky="ew")
        self.folder_path_entry.bind("<KeyRelease>", self._sync_folder_path_changed)
        self.browse_folder_button = self._button(
            destination,
            "选择 Eagle 文件夹",
            self.choose_sync_eagle_folder,
            kind="secondary",
            width=136,
        )
        self.browse_folder_button.grid(row=1, column=2, padx=(0, SPACE["lg"]), pady=(0, SPACE["lg"]))

        self.verify_var = ctk.BooleanVar(value=True)
        self.ignore_archive_var = ctk.BooleanVar(value=False)
        self.force_var = ctk.BooleanVar(value=False)
        self.dry_run_var = ctk.BooleanVar(value=False)
        self.show_annotation_var = ctk.BooleanVar(value=False)

        common = self._card(parent, 3, "3. 常用选项", "⚙", columns=2)
        common.grid_columnconfigure(0, weight=1)
        common.grid_columnconfigure(1, weight=1)
        self._checkbox(common, "同步前检查 Eagle 中是否已存在", self.verify_var).grid(
            row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(common, text="避免重复导入，删除后可重新补导入。", text_color="gray").grid(
            row=2, column=0, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )
        self._checkbox(common, "仅预览，不实际导入", self.dry_run_var).grid(
            row=1, column=1, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(common, text="只显示将要执行的内容。", text_color="gray").grid(
            row=2, column=1, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )

        advanced = self._card(parent, 4, "4. 高级选项", "☷", columns=3)
        for column in range(3):
            advanced.grid_columnconfigure(column, weight=1)
        self._checkbox(advanced, "忽略下载记录，重新下载", self.ignore_archive_var).grid(
            row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(advanced, text="即使以前下载过，也重新下载。", text_color="gray").grid(
            row=2, column=0, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )
        self._checkbox(advanced, "强制重新导入", self.force_var).grid(
            row=1, column=1, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(advanced, text="忽略已导入记录，可能产生重复素材。", text_color="gray").grid(
            row=2, column=1, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )
        self._checkbox(advanced, "显示详细注释", self.show_annotation_var).grid(
            row=1, column=2, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(advanced, text="在日志中显示将写入 Eagle 的完整注释。", text_color=COLORS["text_muted"], font=FONTS["small"]).grid(
            row=2, column=2, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )

        actions = ctk.CTkFrame(
            parent,
            fg_color=COLORS["card"],
            corner_radius=RADIUS["card"],
            border_width=1,
            border_color=COLORS["border"],
        )
        actions.grid(row=5, column=0, sticky="ew", padx=SPACE["md"], pady=(0, SPACE["lg"]))
        for column in range(6):
            actions.grid_columnconfigure(column, weight=1)

        self.sync_button = self._button(actions, "开始同步", self.start_sync, kind="primary", width=140)
        self.sync_button.grid(row=0, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=SPACE["md"], sticky="ew")
        self.preview_button = self._button(actions, "预览", self.preview, width=100)
        self.preview_button.grid(row=0, column=1, padx=SPACE["sm"], pady=SPACE["md"], sticky="ew")
        self.folder_button = self._button(actions, "检查 Eagle 文件夹", self.ensure_folder, width=140)
        self.folder_button.grid(row=0, column=2, padx=SPACE["sm"], pady=SPACE["md"], sticky="ew")
        self.open_staging_button = self._button(actions, "打开缓存目录", self.open_staging_dir, width=128)
        self.open_staging_button.grid(row=0, column=3, padx=SPACE["sm"], pady=SPACE["md"], sticky="ew")
        self.open_config_button = self._button(actions, "打开配置目录", self.open_config_dir, width=128)
        self.open_config_button.grid(row=0, column=4, padx=SPACE["sm"], pady=SPACE["md"], sticky="ew")
        self.open_readme_button = self._button(actions, "打开说明", self.open_readme, width=110)
        self.open_readme_button.grid(row=0, column=5, padx=(SPACE["sm"], SPACE["md"]), pady=SPACE["md"], sticky="ew")

    def _build_settings_tab(self, parent: Any) -> None:
        if getattr(self, "_settings_tab_built", False):
            return
        self._settings_tab_built = True
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self.settings_nav_buttons: dict[str, Any] = {}
        self.settings_nav_after_id: str | None = None
        self.settings_section_widgets: dict[str, Any] = {}
        self.settings_nav_order: tuple[tuple[str, str], ...] = ()

        content = ctk.CTkScrollableFrame(
            parent,
            fg_color=COLORS["surface"],
            corner_radius=RADIUS["card"],
            **SCROLLBAR_STYLE,
        )
        content.grid(row=0, column=0, sticky="nsew", padx=SPACE["md"], pady=0)
        content.grid_columnconfigure(0, weight=1)
        self.settings_content_scroll = content
        self.settings_content_frame = content
        self._bind_scrollable_frame_mousewheel(content)
        parent = content

        ctk.CTkLabel(parent, text="设置中心", text_color=COLORS["text"], font=FONTS["page_title"]).grid(
            row=0, column=0, padx=SPACE["md"], pady=(SPACE["lg"], 4), sticky="w"
        )
        ctk.CTkLabel(
            parent,
            text="管理登录方式、存储路径、网络连接及应用行为设置。",
            text_color=COLORS["text_muted"],
            font=FONTS["body"],
        ).grid(row=1, column=0, padx=SPACE["md"], pady=(0, SPACE["md"]), sticky="w")

        login_card = self._card(parent, 2, "1. Instagram 登录方式", "♙", columns=3)
        self.settings_section_widgets["instagram"] = login_card
        login_card.grid_columnconfigure(0, weight=1)
        login_card.grid_columnconfigure(1, weight=1)
        login_card.grid_columnconfigure(2, weight=1)
        self.login_method = ctk.CTkSegmentedButton(
            login_card,
            values=[LOGIN_COOKIE_FILE, LOGIN_BROWSER, LOGIN_NONE],
            command=self._login_method_changed,
            height=30,
            **SEGMENTED_STYLE,
        )
        self.login_method.grid(row=1, column=0, columnspan=3, padx=SPACE["lg"], pady=(0, SPACE["sm"]), sticky="ew")
        ctk.CTkLabel(
            login_card,
            text=(
                "cookies.txt 文件方式推荐且稳定；浏览器读取可能因 Cookie 加密、Profile 不匹配"
                "或浏览器未关闭而失败；不登录模式只适合部分公开内容。"
            ),
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=2, column=0, columnspan=3, padx=SPACE["lg"], pady=(0, SPACE["md"]), sticky="w")

        self.browser_login_frame = ctk.CTkFrame(
            login_card,
            corner_radius=RADIUS["control"],
            fg_color=COLORS["surface_3"],
            border_width=1,
            border_color=COLORS["border_soft"],
        )
        self.browser_login_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=SPACE["lg"], pady=(0, SPACE["md"]))
        self.browser_login_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.browser_login_frame, text="浏览器选择", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=0, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=SPACE["md"], sticky="w"
        )
        self.browser_choice = ctk.CTkSegmentedButton(
            self.browser_login_frame,
            values=list(BROWSER_LABELS),
            command=self._browser_changed,
            height=28,
            **SEGMENTED_STYLE,
        )
        self.browser_choice.grid(row=0, column=1, padx=(0, SPACE["md"]), pady=SPACE["md"], sticky="w")
        ctk.CTkLabel(self.browser_login_frame, text="Profile", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=1, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=(0, SPACE["md"]), sticky="w"
        )
        self.browser_profile_entry = ctk.CTkComboBox(
            self.browser_login_frame,
            values=["Default"],
            height=INPUT_HEIGHT,
            **COMBOBOX_STYLE,
        )
        self.browser_profile_entry.grid(row=1, column=1, padx=(0, SPACE["sm"]), pady=(0, SPACE["md"]), sticky="ew")
        self.scan_profiles_button = self._button(self.browser_login_frame, "扫描 Profile", self.scan_browser_profiles, width=124)
        self.scan_profiles_button.grid(row=1, column=2, padx=(0, SPACE["md"]), pady=(0, SPACE["md"]), sticky="e")
        ctk.CTkLabel(
            self.browser_login_frame,
            text="读取前请关闭对应浏览器，否则可能失败。",
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=2, column=0, columnspan=3, padx=SPACE["md"], pady=(0, SPACE["md"]), sticky="w")

        self.cookie_file_frame = ctk.CTkFrame(
            login_card,
            corner_radius=RADIUS["control"],
            fg_color=COLORS["surface_3"],
            border_width=1,
            border_color=COLORS["border_soft"],
        )
        self.cookie_file_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=SPACE["lg"], pady=(0, SPACE["md"]))
        self.cookie_file_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.cookie_file_frame,
            text="Instagram 登录 Cookie 文件（备用）",
            text_color=COLORS["text"],
            font=FONTS["label"],
        ).grid(row=0, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=SPACE["md"], sticky="w")
        self.setting_entries["cookies_file"] = self._entry(self.cookie_file_frame)
        self.setting_entries["cookies_file"].grid(row=0, column=1, pady=SPACE["md"], sticky="ew")
        self._button(self.cookie_file_frame, "选择文件", self.choose_cookies_file, width=96).grid(
            row=0, column=2, padx=(SPACE["sm"], SPACE["md"]), pady=SPACE["md"], sticky="e"
        )
        self._button(self.cookie_file_frame, "如何获取 cookies.txt？", self.show_cookie_help, width=160).grid(
            row=1, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=(0, SPACE["md"]), sticky="w"
        )
        ctk.CTkLabel(
            self.cookie_file_frame,
            text="cookies 文件相当于临时登录凭证，请勿分享。",
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=1, column=1, columnspan=2, padx=SPACE["md"], pady=(0, SPACE["md"]), sticky="w")

        self.test_login_button = self._button(login_card, "测试 Instagram 登录状态", self.test_instagram_login, width=180)
        self.test_login_button.grid(row=5, column=0, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="w")

        storage_card = self._card(parent, 3, "2. 下载与缓存路径", "▱", columns=3)
        self.settings_section_widgets["storage"] = storage_card
        storage_card.grid_columnconfigure(1, weight=1)
        self._add_setting_row(
            storage_card,
            1,
            "存储下载文件的父级文件夹",
            STORAGE_PARENT_KEY,
            "选择文件夹",
            self.choose_storage_parent_dir,
        )
        self._add_storage_preview(storage_card, 2)

        connect_card = self._card(parent, 4, "3. 连接与默认值", "◎", columns=4)
        self.settings_section_widgets["eagle"] = connect_card
        for column in range(4):
            connect_card.grid_columnconfigure(column, weight=1)
        self._add_compact_field(connect_card, 1, 0, "Eagle 本地 API 地址", "eagle_api_base")
        self._add_compact_field(connect_card, 1, 2, "请求间隔", "sleep_request")
        self._add_compact_field(
            connect_card,
            2,
            0,
            "默认 Eagle 导入位置",
            "default_folder_path",
            button_text="选择",
            button_command=self.choose_default_eagle_folder,
        )
        self._add_compact_field(connect_card, 2, 2, "作者主页默认最多同步帖子数", "max_posts")
        proxy_frame = self._add_proxy_settings(connect_card, 3)
        self.settings_section_widgets["proxy"] = proxy_frame

        actions = ctk.CTkFrame(connect_card, corner_radius=0, fg_color="transparent")
        actions.grid(row=4, column=0, columnspan=4, sticky="ew", padx=SPACE["lg"], pady=(SPACE["md"], SPACE["lg"]))
        actions.grid_columnconfigure(0, weight=1)
        self.reload_settings_button = self._button(actions, "重新加载", self.reload_settings, width=116)
        self.reload_settings_button.grid(row=0, column=1, padx=SPACE["sm"], pady=0, sticky="e")
        self.save_settings_button = self._button(actions, "保存设置", self.save_settings, kind="primary", width=132)
        self.save_settings_button.grid(row=0, column=2, padx=(SPACE["sm"], 0), pady=0, sticky="e")
        self._bind_scrollable_frame_mousewheel(content)

    def _scroll_settings_to_section(self, section_key: str) -> None:
        widget = getattr(self, "settings_section_widgets", {}).get(section_key)
        canvas = self._settings_scroll_canvas()
        if widget is None or canvas is None:
            self._highlight_settings_nav(section_key)
            return
        try:
            self.update_idletasks()
            y = self._settings_widget_y(widget)
            section_height = self._settings_widget_height(widget)
            scroll_height = self._settings_scroll_height(canvas)
            viewport_height = max(int(canvas.winfo_height()), 1)
            canvas.yview_moveto(
                self._settings_scroll_fraction(
                    section_y=y,
                    section_height=section_height,
                    viewport_height=viewport_height,
                    scroll_height=scroll_height,
                )
            )
        except Exception:  # noqa: BLE001 - navigation should stay best-effort.
            pass
        self._highlight_settings_nav(section_key)
        self._flash_settings_section(section_key)
        self._schedule_settings_nav_update()

    def _schedule_settings_nav_update(self) -> None:
        if not getattr(self, "settings_nav_buttons", None):
            return
        try:
            if self.settings_nav_after_id is not None:
                self.after_cancel(self.settings_nav_after_id)
            self.settings_nav_after_id = self.after(60, self._update_settings_nav_from_scroll)
        except Exception:  # noqa: BLE001 - test doubles may not expose after scheduling.
            self._update_settings_nav_from_scroll()

    def _update_settings_nav_from_scroll(self) -> None:
        self.settings_nav_after_id = None
        active = self._settings_active_section_key()
        if active:
            self._highlight_settings_nav(active)

    def _settings_active_section_key(self) -> str | None:
        canvas = self._settings_scroll_canvas()
        if canvas is None:
            return None
        try:
            visible_top = float(canvas.canvasy(0))
            viewport_height = max(int(canvas.winfo_height()), 1)
            scroll_height = self._settings_scroll_height(canvas)
        except Exception:  # noqa: BLE001 - alternate canvas implementations can differ.
            return None

        ranges = self._settings_section_ranges(scroll_height=scroll_height)
        if not ranges:
            return None

        max_top = max(float(scroll_height - viewport_height), 0.0)
        if max_top > 0 and visible_top >= max_top - 2:
            return ranges[-1][2]

        visible_bottom = visible_top + viewport_height
        anchor_y = visible_top + viewport_height * 0.55
        for start, end, key in ranges:
            if start <= anchor_y < end:
                return key

        best_key = ranges[0][2]
        best_overlap = -1.0
        for start, end, key in ranges:
            overlap = max(0.0, min(end, visible_bottom) - max(start, visible_top))
            if overlap > best_overlap:
                best_overlap = overlap
                best_key = key
        return best_key

    def _settings_section_ranges(self, *, scroll_height: int | None = None) -> list[tuple[float, float, str]]:
        sections = getattr(self, "settings_section_widgets", {})
        if not sections:
            return []

        starts: list[tuple[float, str]] = []
        for key, _label in getattr(self, "settings_nav_order", ()):
            widget = sections.get(key)
            if widget is None:
                continue
            try:
                starts.append((float(self._settings_widget_y(widget)), key))
            except Exception:  # noqa: BLE001 - skip widgets that are not mapped yet.
                continue
        if not starts:
            return []

        starts.sort(key=lambda item: item[0])
        if scroll_height is None:
            canvas = self._settings_scroll_canvas()
            if canvas is not None:
                scroll_height = self._settings_scroll_height(canvas)
            else:
                last_widget = sections.get(starts[-1][1])
                last_height = self._settings_widget_height(last_widget) if last_widget is not None else 1
                scroll_height = int(starts[-1][0] + last_height)

        ranges: list[tuple[float, float, str]] = []
        for index, (start, key) in enumerate(starts):
            if index + 1 < len(starts):
                end = starts[index + 1][0]
            else:
                widget = sections.get(key)
                widget_end = start + (self._settings_widget_height(widget) if widget is not None else 1)
                end = max(float(scroll_height), widget_end)
            ranges.append((start, max(end, start + 1), key))
        return ranges

    def _settings_scroll_canvas(self) -> Any | None:
        scroll = self.__dict__.get("settings_content_scroll") or self.__dict__.get("settings_tab")
        return getattr(scroll, "_parent_canvas", None)

    def _highlight_settings_nav(self, active_key: str) -> None:
        for key, button in getattr(self, "settings_nav_buttons", {}).items():
            selected = key == active_key
            try:
                button.configure(
                    fg_color=COLORS["selection"] if selected else "transparent",
                    text_color=COLORS["text"] if selected else COLORS["text_muted"],
                )
            except Exception:  # noqa: BLE001 - tests may use lightweight doubles.
                continue

    def _flash_settings_section(self, section_key: str) -> None:
        widget = getattr(self, "settings_section_widgets", {}).get(section_key)
        if widget is None:
            return
        original = {
            "border_color": self._safe_widget_cget(widget, "border_color", COLORS["border"]),
            "border_width": self._safe_widget_cget(widget, "border_width", 1),
        }
        try:
            widget.configure(border_color=COLORS["primary_soft"], border_width=2)
        except Exception:  # noqa: BLE001 - not all anchors expose border options.
            return

        def restore() -> None:
            try:
                widget.configure(**original)
            except Exception:  # noqa: BLE001 - best effort visual feedback.
                pass

        for delay, color_key in SETTINGS_SECTION_FLASH_STEPS[1:]:
            def apply_step(key: str = color_key) -> None:
                try:
                    widget.configure(border_color=COLORS[key], border_width=2)
                except Exception:  # noqa: BLE001 - best effort visual feedback.
                    pass

            try:
                self.after(delay, apply_step)
            except Exception:  # noqa: BLE001 - tests may not provide Tk scheduling.
                apply_step()
        try:
            self.after(860, restore)
        except Exception:  # noqa: BLE001 - tests may not provide Tk scheduling.
            restore()

    @staticmethod
    def _safe_widget_cget(widget: Any, key: str, fallback: Any) -> Any:
        try:
            value = widget.cget(key)
        except Exception:  # noqa: BLE001 - CustomTkinter/test doubles differ.
            return fallback
        return fallback if value is None else value

    def _settings_widget_y(self, widget: Any) -> int:
        content = getattr(self, "settings_content_frame", None)
        y = 0
        current = widget
        while current is not None and current is not content:
            y += int(current.winfo_y())
            try:
                current = current.master
            except Exception:  # noqa: BLE001 - fallback for widgets without master.
                break
        if content is not None:
            try:
                y += int(content.winfo_y())
            except Exception:  # noqa: BLE001 - content may be a test double.
                pass
        return max(y - SPACE["md"], 0)

    @staticmethod
    def _settings_widget_height(widget: Any) -> int:
        for method_name in ("winfo_height", "winfo_reqheight"):
            try:
                height = int(getattr(widget, method_name)())
            except Exception:  # noqa: BLE001 - try the next Tk geometry method.
                continue
            if height > 1:
                return height
        return 1

    @staticmethod
    def _settings_scroll_fraction(
        *,
        section_y: int,
        section_height: int,
        viewport_height: int,
        scroll_height: int,
    ) -> float:
        if scroll_height <= 0:
            return 0.0
        viewport_height = max(viewport_height, 1)
        section_height = max(section_height, 1)
        if section_height <= viewport_height * 0.75:
            offset = min(max(int((viewport_height - section_height) * 0.28), SETTINGS_SCROLL_TOP_PADDING), 96)
        else:
            offset = SETTINGS_SCROLL_TOP_PADDING
        max_top = max(scroll_height - viewport_height, 0)
        desired_top = min(max(section_y - offset, 0), max_top)
        return min(max(desired_top / scroll_height, 0.0), 1.0)

    @staticmethod
    def _settings_scroll_height(canvas: Any) -> int:
        try:
            bbox = canvas.bbox("all")
            if bbox:
                return max(int(bbox[3] - bbox[1]), 1)
        except Exception:  # noqa: BLE001 - fallback below.
            pass
        try:
            return max(int(canvas.winfo_reqheight()), int(canvas.winfo_height()), 1)
        except Exception:  # noqa: BLE001 - final fallback.
            return 1

    def _add_setting_row(
        self,
        parent: Any,
        row: int,
        label: str,
        key: str,
        button_text: str | None = None,
        button_command: Callable[[], None] | None = None,
    ) -> None:
        ctk.CTkLabel(parent, text=label, text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=row, column=0, padx=SPACE["lg"], pady=SPACE["sm"], sticky="w"
        )
        entry = self._entry(parent)
        entry.grid(row=row, column=1, pady=SPACE["sm"], sticky="ew")
        self.setting_entries[key] = entry
        if button_text and button_command:
            button = self._button(parent, button_text, button_command, width=108)
            button.grid(row=row, column=2, padx=(SPACE["sm"], SPACE["lg"]), pady=SPACE["sm"], sticky="e")

    def _add_compact_field(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        *,
        button_text: str | None = None,
        button_command: Callable[[], None] | None = None,
    ) -> None:
        ctk.CTkLabel(parent, text=label, text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=row, column=column, padx=(SPACE["lg"], SPACE["sm"]), pady=SPACE["sm"], sticky="w"
        )
        if button_text and button_command:
            field = ctk.CTkFrame(parent, fg_color="transparent")
            field.grid(row=row, column=column + 1, padx=(0, SPACE["lg"]), pady=SPACE["sm"], sticky="ew")
            field.grid_columnconfigure(0, weight=1)
            entry = self._entry(field)
            entry.grid(row=0, column=0, padx=(0, SPACE["sm"]), sticky="ew")
            self._button(field, button_text, button_command, width=72).grid(row=0, column=1, sticky="e")
        else:
            entry = self._entry(parent)
            entry.grid(row=row, column=column + 1, padx=(0, SPACE["lg"]), pady=SPACE["sm"], sticky="ew")
        self.setting_entries[key] = entry
        if key == "default_folder_path":
            entry.bind("<KeyRelease>", self._default_folder_path_changed)

    def _add_proxy_settings(self, parent: Any, row: int) -> Any:
        frame = ctk.CTkFrame(
            parent,
            corner_radius=RADIUS["control"],
            fg_color=COLORS["surface_3"],
            border_width=1,
            border_color=COLORS["border_soft"],
        )
        frame.grid(row=row, column=0, columnspan=4, sticky="ew", padx=SPACE["lg"], pady=SPACE["sm"])
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="代理设置", text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=0, columnspan=3, padx=SPACE["md"], pady=(SPACE["md"], SPACE["sm"]), sticky="w"
        )
        self.proxy_mode = ctk.CTkSegmentedButton(
            frame,
            values=list(PROXY_MODE_VALUES),
            command=self._proxy_mode_changed,
            height=30,
            **SEGMENTED_STYLE,
        )
        self.proxy_mode.grid(row=1, column=0, columnspan=3, padx=SPACE["md"], pady=(0, SPACE["sm"]), sticky="ew")

        self.proxy_auto_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.proxy_auto_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=SPACE["md"], pady=(0, SPACE["sm"]))
        self.proxy_auto_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.proxy_auto_frame,
            text="自动读取 Windows 或环境变量中的代理设置，适合大多数用户。",
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, SPACE["xs"]))
        self._button(self.proxy_auto_frame, "立即检测", self.detect_proxy_now, width=96).grid(
            row=1, column=0, padx=(0, SPACE["sm"]), sticky="w"
        )
        ctk.CTkLabel(
            self.proxy_auto_frame,
            textvariable=self.proxy_detect_result_var,
            text_color=COLORS["text_muted"],
            font=FONTS["body"],
        ).grid(row=1, column=1, sticky="w")

        self.proxy_manual_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.proxy_manual_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=SPACE["md"], pady=(0, SPACE["sm"]))
        self.proxy_manual_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self.proxy_manual_frame,
            text="如果你知道自己的代理地址，可以手动填写，例如 http://127.0.0.1:10809。",
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, SPACE["xs"]))
        ctk.CTkLabel(self.proxy_manual_frame, text="HTTP 代理", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=1, column=0, padx=(0, SPACE["sm"]), pady=SPACE["xs"], sticky="w"
        )
        self.setting_entries["http_proxy"] = self._entry(self.proxy_manual_frame)
        self.setting_entries["http_proxy"].grid(row=1, column=1, padx=(0, SPACE["sm"]), pady=SPACE["xs"], sticky="ew")
        ctk.CTkLabel(self.proxy_manual_frame, text="HTTPS 代理", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=2, column=0, padx=(0, SPACE["sm"]), pady=SPACE["xs"], sticky="w"
        )
        self.setting_entries["https_proxy"] = self._entry(self.proxy_manual_frame)
        self.setting_entries["https_proxy"].grid(row=2, column=1, padx=(0, SPACE["sm"]), pady=SPACE["xs"], sticky="ew")
        self._button(self.proxy_manual_frame, "清空代理", self.clear_proxy_fields, width=96).grid(
            row=1, column=2, rowspan=2, sticky="e"
        )

        self.proxy_none_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.proxy_none_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=SPACE["md"], pady=(0, SPACE["md"]))
        ctk.CTkLabel(
            self.proxy_none_frame,
            text="直接连接网络，适合无需代理的网络环境。",
            text_color=COLORS["text_muted"],
            font=FONTS["small"],
        ).grid(row=0, column=0, sticky="w")
        return frame

    def _add_storage_preview(self, parent: Any, row: int) -> None:
        frame = ctk.CTkFrame(
            parent,
            corner_radius=RADIUS["control"],
            fg_color=COLORS["surface_3"],
            border_width=1,
            border_color=COLORS["border_soft"],
        )
        frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=SPACE["lg"], pady=(SPACE["sm"], SPACE["lg"]))
        for column in range(3):
            frame.grid_columnconfigure(column, weight=1)
        ctk.CTkLabel(frame, text="将自动使用以下路径", text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=0, columnspan=3, padx=SPACE["md"], pady=(SPACE["md"], SPACE["sm"]), sticky="w"
        )
        rows = (
            ("下载缓存目录", "staging_dir"),
            ("下载记录数据库", "archive_db"),
            ("Eagle 导入记录", "imported_state"),
        )
        for index, (label, key) in enumerate(rows):
            tile = ctk.CTkFrame(
                frame,
                corner_radius=RADIUS["control"],
                fg_color=COLORS["input"],
                border_width=1,
                border_color=COLORS["border_soft"],
            )
            tile.grid(row=1, column=index, padx=SPACE["sm"], pady=(0, SPACE["md"]), sticky="nsew")
            ctk.CTkLabel(tile, text=label, text_color=COLORS["text"], font=FONTS["label"]).grid(
                row=0, column=0, padx=SPACE["md"], pady=(SPACE["sm"], 2), sticky="w"
            )
            ctk.CTkLabel(tile, textvariable=self.storage_preview_vars[key], text_color=COLORS["text_muted"], font=FONTS["small"]).grid(
                row=1, column=0, padx=SPACE["md"], pady=(0, SPACE["sm"]), sticky="w"
            )

    def _set_default_values(self) -> None:
        self.mode.set(MODE_POST)
        sync_folder = get_last_or_default_folder(self.config_data)
        self.selected_folder_id = sync_folder["folder_id"] or None
        self.selected_default_folder_id = get_config_value(self.config_data, "default_folder_id") or None
        self._set_entry(self.folder_path_entry, sync_folder["folder_path"])
        self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
        self._set_entry(self.anchor_date_entry, today_iso())
        self._set_entry(self.date_range_amount_entry, "1")
        self.author_range_choice.set(AUTHOR_SYNC_UNLIMITED)
        self.date_range_choice.set(DATE_RANGE_DAY)
        self._populate_settings_form()
        self._sync_mode_changed(MODE_POST)
        self._author_range_changed(AUTHOR_SYNC_UNLIMITED)

    def _load_config(self) -> AppConfig:
        try:
            return load_config(self.config_path)
        except Exception as exc:  # noqa: BLE001 - visible GUI error, then re-raise to prevent half-init.
            raise RuntimeError(f"读取配置失败：{self.config_path}：{exc}") from exc

    def _populate_settings_form(self) -> None:
        values = {
            "cookies_file": get_config_value(self.config_data, "cookies_file"),
            STORAGE_PARENT_KEY: get_config_value(self.config_data, STORAGE_PARENT_KEY),
            "eagle_api_base": get_config_value(self.config_data, "eagle_api_base"),
            "default_folder_path": get_config_value(self.config_data, "default_folder_path"),
            "http_proxy": get_config_value(self.config_data, "http_proxy"),
            "https_proxy": get_config_value(self.config_data, "https_proxy"),
            "max_posts": str(get_config_value(self.config_data, "max_posts")),
            "sleep_request": get_config_value(self.config_data, "sleep_request"),
        }
        for key, value in values.items():
            self._set_entry(self.setting_entries[key], str(value or ""))
        method, browser_label, profile = get_login_form_values(self.config_data)
        self.selected_default_folder_id = get_config_value(self.config_data, "default_folder_id") or None
        self.proxy_mode.set(PROXY_VALUE_TO_MODE.get(get_config_value(self.config_data, "proxy_mode"), PROXY_AUTO))
        detected_proxy = get_config_value(self.config_data, "detected_proxy")
        self.proxy_detect_result_var.set(
            f"当前检测结果：已检测到 {detected_proxy}" if detected_proxy else "当前检测结果：未检测"
        )
        self._proxy_mode_changed(self.proxy_mode.get())
        self.login_method.set(method)
        self.browser_choice.set(browser_label)
        self.browser_profile_entry.set(profile)
        self._login_method_changed(method)
        self._update_storage_preview()

    def choose_cookies_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self._set_entry(self.setting_entries["cookies_file"], path)
            self.login_method.set(LOGIN_COOKIE_FILE)
            self._login_method_changed(LOGIN_COOKIE_FILE)

    def choose_storage_parent_dir(self) -> None:
        path = filedialog.askdirectory(title="选择存储下载文件的父级文件夹")
        if path:
            self._set_storage_parent(path)

    def detect_proxy_now(self) -> None:
        detected = detect_system_proxy()
        proxy = (detected or {}).get("http") or (detected or {}).get("https") or ""
        if proxy:
            self.proxy_detect_result_var.set(f"当前检测结果：已检测到 {proxy}")
            self._append_log(f"正常：已检测到系统代理：{proxy}")
        else:
            self.proxy_detect_result_var.set("当前检测结果：未检测到系统代理")
            self._append_log("未检测到系统代理。你可以切换到“手动设置代理”，或选择“不使用代理”。")

    def clear_proxy_fields(self) -> None:
        self._set_entry(self.setting_entries["http_proxy"], "")
        self._set_entry(self.setting_entries["https_proxy"], "")
        self._append_log("代理设置已清空。")

    def save_settings(self) -> None:
        try:
            data = self._collect_settings_data(require_storage_parent=True)
            if data is None:
                return
            write_config_data(data, get_runtime_config_path())
            self.config_path = get_runtime_config_path()
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            sync_folder = get_last_or_default_folder(self.config_data)
            self.selected_folder_id = sync_folder["folder_id"] or None
            self._set_entry(self.folder_path_entry, sync_folder["folder_path"])
            self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
            self._sync_mode_changed()
            self._append_log("设置已保存到 config.json。")
            self._warn_about_cookies()
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"错误：保存设置失败：{exc}")

    def reload_settings(self) -> None:
        try:
            self.config_path = ensure_config_file(get_runtime_config_path(), get_runtime_example_config_path())
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            sync_folder = get_last_or_default_folder(self.config_data)
            self.selected_folder_id = sync_folder["folder_id"] or None
            self._set_entry(self.folder_path_entry, sync_folder["folder_path"])
            self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
            self._sync_mode_changed()
            self._append_log(f"设置已重新加载：{self.config_path}")
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"错误：重新加载设置失败：{exc}")

    def _collect_settings_data(self, *, require_storage_parent: bool = True) -> dict[str, Any] | None:
        eagle_api_base = self._setting_value("eagle_api_base")
        folder_path = self._setting_value("default_folder_path")
        max_posts_text = self._setting_value("max_posts")
        sleep_request = self._setting_value("sleep_request")

        if not eagle_api_base:
            self._append_log("错误：Eagle 本地 API 地址不能为空。")
            return None
        if not folder_path:
            self._append_log("错误：默认 Eagle 导入位置不能为空。")
            return None
        if not sleep_request:
            self._append_log("错误：请求间隔不能为空。")
            return None
        try:
            max_posts = int(max_posts_text)
        except ValueError:
            self._append_log("错误：默认最多同步帖子数必须是数字。")
            return None
        if max_posts == 0 or max_posts < -1:
            self._append_log("错误：默认最多同步帖子数必须是 -1 或大于 0 的数字。")
            return None

        data = normalize_config_data(self.config_data)
        http_proxy = self._setting_value("http_proxy")
        https_proxy = self._setting_value("https_proxy")
        storage_parent = self._setting_value(STORAGE_PARENT_KEY)

        if require_storage_parent and not storage_parent:
            storage_parent = self._prompt_for_storage_parent()
            if storage_parent is None:
                return None
        if storage_parent:
            data = apply_storage_parent(data, storage_parent)
        data["eagle_api_base"] = eagle_api_base.rstrip("/")
        data["default_eagle_root_folder"] = folder_path
        data["default_eagle_folder_path"] = folder_path
        data["default_eagle_folder_id"] = self.selected_default_folder_id or ""
        data = apply_login_settings(
            data,
            method=self.login_method.get(),
            browser_label=self.browser_choice.get(),
            profile=self.browser_profile_entry.get().strip(),
            cookie_file=self._setting_value("cookies_file"),
        )
        if self.login_method.get() == LOGIN_COOKIE_FILE:
            cookie_file = self._setting_value("cookies_file")
            if not cookie_file:
                self._append_log("警告：Instagram 登录 Cookie 文件未设置，部分内容可能需要登录。")
            elif not Path(cookie_file).exists():
                self._append_log("警告：Instagram 登录 Cookie 文件不存在：<hidden>")
        data = apply_proxy_settings(
            data,
            mode_label=self.proxy_mode.get(),
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            detected_result=self.proxy_detect_result_var.get(),
        )
        data["download"]["max_posts"] = max_posts
        data["download"]["sleep_request"] = sleep_request
        return data

    def _setting_value(self, key: str) -> str:
        return self.setting_entries[key].get().strip()

    def _set_storage_parent(self, path: str | Path) -> None:
        self._set_entry(self.setting_entries[STORAGE_PARENT_KEY], str(path))
        self._update_storage_preview()

    def _update_storage_preview(self) -> None:
        parent = self._setting_value(STORAGE_PARENT_KEY) if STORAGE_PARENT_KEY in self.setting_entries else ""
        if not parent:
            for var in self.storage_preview_vars.values():
                var.set("未设置")
            return
        paths = build_storage_paths(parent)
        for key, value in paths.items():
            if key in self.storage_preview_vars:
                self.storage_preview_vars[key].set(str(value))

    def _prompt_for_storage_parent(self) -> str | None:
        show_centered_info(
            self,
            "选择存储目录",
            "请先选择“存储下载文件的父级文件夹”。本工具会在其中自动创建 _staging 和 _cache。",
        )
        path = filedialog.askdirectory(title="选择存储下载文件的父级文件夹")
        if not path:
            self._append_log("提示：未选择存储下载文件的父级文件夹。")
            return None
        self._set_storage_parent(path)
        return path

    def _ensure_storage_parent_configured(self) -> bool:
        if get_config_value(self.config_data, STORAGE_PARENT_KEY):
            return True
        parent = self._prompt_for_storage_parent()
        if parent is None:
            return False
        try:
            data = apply_storage_parent(self.config_data, parent)
            write_config_data(data, get_runtime_config_path())
            self.config_path = get_runtime_config_path()
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            self._append_log("存储目录已保存到 config.json。")
            return True
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"错误：保存存储目录失败：{exc}")
            return False

    def _sync_mode_changed(self, value: str | None = None) -> None:
        mode = value or self.mode.get()
        if mode == MODE_AUTHOR:
            self.author_options_panel.grid()
            self._author_range_changed()
        else:
            self.author_options_panel.grid_remove()

    def _author_range_changed(self, value: str | None = None) -> None:
        range_mode = value or self.author_range_choice.get()
        if range_mode == AUTHOR_SYNC_RECENT:
            self.recent_posts_frame.grid()
            self.date_options_frame.grid_remove()
        elif range_mode == AUTHOR_SYNC_DATE_RANGE:
            self.recent_posts_frame.grid_remove()
            self.date_options_frame.grid()
        else:
            self.recent_posts_frame.grid_remove()
            self.date_options_frame.grid_remove()

    def _browser_changed(self, value: str | None = None) -> None:
        browser_label = value or self.browser_choice.get()
        profiles = scan_browser_profiles(browser_label)
        if profiles:
            self.browser_profile_entry.configure(values=profiles)
            if self.browser_profile_entry.get() not in profiles:
                self.browser_profile_entry.set(profiles[0])

    def _login_method_changed(self, value: str | None = None) -> None:
        method = value or self.login_method.get()
        if method == LOGIN_BROWSER:
            self.browser_login_frame.grid()
            self.cookie_file_frame.grid_remove()
        elif method == LOGIN_COOKIE_FILE:
            self.browser_login_frame.grid_remove()
            self.cookie_file_frame.grid()
        else:
            self.browser_login_frame.grid_remove()
            self.cookie_file_frame.grid_remove()

    def _proxy_mode_changed(self, value: str | None = None) -> None:
        mode = value or self.proxy_mode.get()
        if mode == PROXY_MANUAL:
            self.proxy_auto_frame.grid_remove()
            self.proxy_manual_frame.grid()
            self.proxy_none_frame.grid_remove()
        elif mode == PROXY_NONE:
            self.proxy_auto_frame.grid_remove()
            self.proxy_manual_frame.grid_remove()
            self.proxy_none_frame.grid()
        else:
            self.proxy_auto_frame.grid()
            self.proxy_manual_frame.grid_remove()
            self.proxy_none_frame.grid_remove()

    def scan_browser_profiles(self) -> None:
        browser_label = self.browser_choice.get()
        profiles = scan_browser_profiles(browser_label)
        if profiles:
            self.browser_profile_entry.configure(values=profiles)
            self.browser_profile_entry.set(profiles[0])
            self._append_log(f"已找到 {browser_label} Profile：{', '.join(profiles)}")
        else:
            self._append_log("没有找到浏览器 Cookies 数据库。请确认已在浏览器中登录 Instagram，或改用 cookies.txt 文件。")

    def show_cookie_help(self) -> None:
        if ctk is None:
            return
        window = ctk.CTkToplevel(self)
        window.title("如何获取 cookies.txt？")
        window.configure(fg_color=COLORS["window"])
        center_window(window, 680, 420)
        window.transient(self)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)
        text = ctk.CTkTextbox(window, wrap="word", border_width=1, **TEXTBOX_STYLE)
        text.grid(row=0, column=0, sticky="nsew", padx=SPACE["md"], pady=(SPACE["md"], SPACE["sm"]))
        text.insert("end", cookie_help_text())
        text.configure(state="disabled")
        actions = ctk.CTkFrame(window, corner_radius=0, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=SPACE["md"], pady=(0, SPACE["md"]))
        ctk.CTkButton(
            actions,
            text="打开插件下载页",
            command=open_cookie_help_url,
            height=BUTTON_HEIGHT,
            corner_radius=RADIUS["control"],
            font=FONTS["button"],
            **BUTTON_STYLES["primary"],
        ).grid(
            row=0, column=0, padx=(0, SPACE["sm"]), pady=SPACE["sm"]
        )
        ctk.CTkButton(
            actions,
            text="关闭",
            command=window.destroy,
            height=BUTTON_HEIGHT,
            corner_radius=RADIUS["control"],
            font=FONTS["button"],
            **BUTTON_STYLES["secondary"],
        ).grid(row=0, column=1, padx=SPACE["sm"], pady=SPACE["sm"])
        try:
            window.lift()
            window.focus_force()
        except Exception:  # noqa: BLE001 - focus behavior varies by platform/window manager.
            pass

    def test_instagram_login(self) -> None:
        data = self._collect_settings_data(require_storage_parent=False)
        if data is None:
            return
        config = parse_config(data)
        url = self.url_entry.get().strip() or DEFAULT_LOGIN_TEST_URL

        def task() -> dict[str, Any]:
            messages = run_instagram_login_check(config, url)
            for message in messages:
                self._queue_log(message)
            failed = any(message.startswith("警告：") or message.startswith("错误：") for message in messages)
            if failed and config.cookies.from_browser and not self.browser_cookie_help_prompted:
                self.browser_cookie_help_prompted = True
                self.log_queue.put(SHOW_BROWSER_COOKIE_HELP)
            return {
                "ok": not failed,
                "messages": messages,
            }

        self._start_worker("测试 Instagram 登录状态", task)

    def startup_checks(self) -> None:
        def run() -> None:
            if self.icon_status_message:
                self._queue_log(self.icon_status_message)
            for message in run_startup_checks(self.config):
                self._queue_log(message)

        threading.Thread(target=run, daemon=True).start()

    def clear_log(self) -> None:
        self.log_text.delete("1.0", "end")
        self.log_line_count = 0

    def copy_log(self) -> None:
        try:
            text = self.log_text.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(text)
            self._append_log("日志已复制到剪贴板。")
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"错误：复制日志失败：{exc}")

    def toggle_log_panel(self) -> None:
        if self.log_panel_visible:
            self.log_panel.grid_remove()
            self.log_panel_visible = False
            self.toggle_log_button.configure(text="显示日志")
            return

        self.log_panel.grid()
        self.log_panel_visible = True
        self.toggle_log_button.configure(text="隐藏日志")
        self.log_text.see("end")

    def preview(self) -> None:
        self._run_sync_task(force_dry_run=True)

    def start_sync(self) -> None:
        self._run_sync_task(force_dry_run=False)

    def choose_sync_eagle_folder(self) -> None:
        self._open_eagle_folder_picker(
            initial_folder_id=self.selected_folder_id,
            on_select=self._apply_sync_folder_selection,
        )

    def choose_default_eagle_folder(self) -> None:
        self._open_eagle_folder_picker(
            initial_folder_id=self.selected_default_folder_id,
            on_select=self._apply_default_folder_selection,
        )

    def _open_eagle_folder_picker(
        self,
        *,
        initial_folder_id: str | None,
        on_select: Callable[[dict[str, str]], None],
    ) -> None:
        if not self.config.eagle_api_base:
            message = "无法连接 Eagle。请先打开 Eagle，并确认本地 API 地址正确。"
            self._append_log(message)
            return
        try:
            EagleFolderPickerDialog(
                self,
                config=self.config,
                initial_folder_id=initial_folder_id,
                on_select=on_select,
                log=self._append_log,
            )
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(folder_picker_error_message([str(exc)]))

    def _apply_sync_folder_selection(self, selection: dict[str, str]) -> None:
        self.selected_folder_id = selection.get("folder_id") or None
        self._set_entry(self.folder_path_entry, selection.get("folder_path") or "")
        self._remember_last_eagle_folder(selection)
        self._append_log(f"已选择 Eagle 文件夹：{selection.get('folder_path')}")

    def _apply_default_folder_selection(self, selection: dict[str, str]) -> None:
        self.selected_default_folder_id = selection.get("folder_id") or None
        self._set_entry(self.setting_entries["default_folder_path"], selection.get("folder_path") or "")
        self._append_log(f"已选择默认 Eagle 文件夹：{selection.get('folder_path')}")

    def _sync_folder_path_changed(self, _event: object | None = None) -> None:
        self.selected_folder_id = None

    def _default_folder_path_changed(self, _event: object | None = None) -> None:
        self.selected_default_folder_id = None

    def _remember_last_eagle_folder(self, selection: dict[str, str]) -> None:
        try:
            data = apply_last_eagle_folder(self.config_data, selection)
            write_config_data(data, get_runtime_config_path())
            self.config_path = get_runtime_config_path()
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
        except Exception as exc:  # noqa: BLE001 - remembering should not block selection.
            self._append_log(f"警告：无法记住上次选择的 Eagle 文件夹：{exc}")

    def ensure_folder(self) -> None:
        folder_path = self.folder_path_entry.get().strip()
        if not folder_path:
            self._append_log("错误：Eagle 导入位置不能为空。")
            return
        if not self.config.eagle_api_base:
            self._append_log("错误：Eagle 本地 API 地址不能为空。")
            return

        def task() -> dict[str, Any]:
            return services.ensure_folder(self.config, folder_path)

        self._start_worker("检查 Eagle 文件夹", task)

    def open_staging_dir(self) -> None:
        if not self._ensure_storage_parent_configured():
            return
        try:
            path = self._target_staging_dir()
        except Exception as exc:  # noqa: BLE001 - user-facing log.
            self._append_log(f"错误：{exc}")
            return

        if not path.exists():
            self._append_log(f"提示：缓存目录不存在：{path}")
            return

        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self._append_log(f"已打开缓存目录：{path}")
        except Exception as exc:  # noqa: BLE001 - user-facing log.
            self._append_log(f"错误：无法打开缓存目录 {path}：{exc}")

    def open_config_dir(self) -> None:
        self._open_path(Path(self.config_path).resolve().parent, "配置目录")

    def open_readme(self) -> None:
        readme_path = get_runtime_readme_path().resolve()
        if not readme_path.exists():
            self._append_log(f"提示：README.md 不存在：{readme_path}")
            return
        self._open_path(readme_path, "说明文档")

    def _open_path(self, path: Path, label: str) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self._append_log(f"已打开 {label}：{path}")
        except Exception as exc:  # noqa: BLE001 - user-facing log.
            self._append_log(f"错误：无法打开 {label}：{exc}")

    def _run_sync_task(self, *, force_dry_run: bool) -> None:
        if not self._ensure_storage_parent_configured():
            return
        url = self.url_entry.get().strip()
        folder_path = self.folder_path_entry.get().strip()
        if not url:
            self._append_log("错误：Instagram 链接不能为空。")
            return
        if not folder_path:
            self._append_log("错误：Eagle 导入位置不能为空。")
            return
        if not self.config.eagle_api_base:
            self._append_log("错误：Eagle 本地 API 地址不能为空。")
            return

        self._warn_about_cookies()
        dry_run = True if force_dry_run else self.dry_run_var.get()
        mode = self.mode.get()
        try:
            normalized_url = detect_instagram_url(url).normalized_url
        except ValueError as exc:
            self._append_log(f"错误：{exc}")
            return
        max_posts: int | None = None
        date_from: str | None = None
        date_to: str | None = None
        if mode == MODE_AUTHOR:
            author_range = self._read_author_sync_range()
            if author_range is False:
                return
            max_posts, date_from, date_to = author_range

        def task() -> dict[str, Any]:
            selected_folder_id = self.selected_folder_id
            kwargs = {
                "folder_id": selected_folder_id,
                "folder_path": None if selected_folder_id else folder_path,
                "dry_run": dry_run,
                "force": self.force_var.get(),
                "verify_eagle": self.verify_var.get(),
                "show_annotation": self.show_annotation_var.get(),
                "ignore_archive": self.ignore_archive_var.get(),
                "log": self._queue_log,
            }
            if mode == MODE_AUTHOR:
                return services.sync_author(
                    self.config,
                    normalized_url,
                    max_posts=max_posts,
                    date_from=date_from,
                    date_to=date_to,
                    **kwargs,
                )
            return services.sync_post(self.config, normalized_url, **kwargs)

        title = "预览" if force_dry_run else "同步"
        self._start_worker(title, task)

    def _read_max_posts(self) -> int | None | bool:
        raw = self.max_posts_entry.get().strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            self._append_log("错误：最多同步帖子数必须是数字。")
            return False
        if value == 0 or value < -1:
            self._append_log("错误：最多同步帖子数必须是 -1 或大于 0 的数字。")
            return False
        return value

    def _read_recent_posts_count(self) -> int | bool:
        raw = self.max_posts_entry.get().strip()
        try:
            value = int(raw)
        except ValueError:
            self._append_log("错误：最近同步帖子数必须是数字。")
            return False
        if value <= 0:
            self._append_log("错误：最近同步帖子数必须大于 0。")
            return False
        return value

    def _read_author_sync_range(self) -> tuple[int | None, str | None, str | None] | bool:
        range_mode = self.author_range_choice.get() if hasattr(self, "author_range_choice") else AUTHOR_SYNC_UNLIMITED
        if range_mode == AUTHOR_SYNC_RECENT:
            max_posts = self._read_recent_posts_count()
            if max_posts is False:
                return False
            return max_posts, None, None
        if range_mode == AUTHOR_SYNC_DATE_RANGE:
            date_range = self._read_date_range()
            if date_range is False:
                return False
            date_from, date_to = date_range
            return -1, date_from, date_to
        return -1, None, None

    def _read_date_range(self) -> tuple[str, str] | bool:
        anchor_date = self.anchor_date_entry.get().strip() if hasattr(self, "anchor_date_entry") else today_iso()
        range_label = self.date_range_choice.get() if hasattr(self, "date_range_choice") else DATE_RANGE_DAY
        range_amount_text = (
            self.date_range_amount_entry.get().strip() if hasattr(self, "date_range_amount_entry") else "1"
        )
        try:
            range_amount = int(range_amount_text or "1")
        except ValueError:
            self._append_log("错误：时间范围数量必须是数字。")
            return False
        try:
            return author_date_range(anchor_date, range_label, range_amount)
        except ValueError as exc:
            self._append_log(f"错误：{exc}")
            return False

    def _target_staging_dir(self) -> Path:
        url = self.url_entry.get().strip()
        if not url:
            return self.config.staging_dir

        info = detect_instagram_url(url)
        if self.mode.get() == MODE_AUTHOR:
            if info.mode != InstagramMode.AUTHOR or not info.username:
                raise ValueError("作者主页模式需要填写 Instagram 作者主页链接。")
            return self.config.staging_dir / info.username

        if info.mode != InstagramMode.POST or not info.shortcode:
            raise ValueError("单个帖子模式需要填写 Instagram 帖子或 Reel 链接。")
        return self.config.staging_dir / "unknown" / info.shortcode

    def _warn_about_cookies(self) -> None:
        if not self.config.cookies.enabled:
            return
        if self.config.cookies.from_browser:
            return
        cookie_file = self.config.cookies.file
        if cookie_file is None:
            self._append_log("警告：Instagram 登录 Cookie 文件未设置，部分内容可能需要登录。")
            return
        if not cookie_file.exists():
            self._append_log("警告：Instagram 登录 Cookie 文件不存在：<hidden>")

    def _start_worker(self, label: str, task: Callable[[], dict[str, Any]]) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._append_log("提示：当前已有任务正在运行。")
            return

        self.browser_cookie_help_prompted = False
        self._set_controls_enabled(False)
        self._set_status(STATUS_RUNNING)
        self._append_log("")
        self._append_log(f"== {label}开始 ==")

        def run() -> None:
            done_message = "__TASK_DONE_FAILED__"
            try:
                result = task()
                done_message = "__TASK_DONE_OK__" if result.get("ok") else "__TASK_DONE_FAILED__"
                self._queue_log(f"== {label}结束：{'成功' if result.get('ok') else '失败'} ==")
                self._queue_summary(result)
            except Exception:
                self._queue_log("错误：任务运行时发生异常")
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
        sanitized = self._sanitize_log_message(message)
        self.log_queue.put(sanitized)
        if should_show_login_failure_hint(sanitized):
            self.log_queue.put(FRIENDLY_LOGIN_FAILURE_HINT)
            if self.config.cookies.from_browser and not self.browser_cookie_help_prompted:
                self.browser_cookie_help_prompted = True
                self.log_queue.put(SHOW_BROWSER_COOKIE_HELP)

    def _drain_log_queue(self) -> None:
        if self.__dict__.get("_is_resizing", False):
            if self.__dict__.get("_resize_debug_enabled", False):
                self.resize_debug_stats["log_flush_deferred"] += 1
            self.after(LOG_FLUSH_RESIZE_DELAY_MS, self._drain_log_queue)
            return

        log_messages: list[str] = []
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
            elif message == SHOW_BROWSER_COOKIE_HELP:
                self._show_browser_cookie_help_prompt()
            else:
                log_messages.append(message)
                if len(log_messages) >= LOG_BATCH_LIMIT:
                    break

        if log_messages:
            self._append_log_batch(log_messages)

        self.after(LOG_FLUSH_INTERVAL_MS, self._drain_log_queue)

    def _show_browser_cookie_help_prompt(self) -> None:
        show_centered_warning(
            self,
            "浏览器读取失败",
            "自动从浏览器读取登录状态失败。建议改用 cookies.txt 文件方式。\n\n"
            "程序将切换到 cookies.txt 模式，并打开获取 cookies.txt 的说明。",
        )
        try:
            self.login_method.set(LOGIN_COOKIE_FILE)
            self._login_method_changed(LOGIN_COOKIE_FILE)
        except Exception:  # noqa: BLE001 - keep the help dialog available even if widgets are unavailable.
            pass
        self.show_cookie_help()

    def _append_log(self, message: object) -> None:
        self._append_log_batch([self._sanitize_log_message(message)])

    def _append_log_batch(self, messages: list[object]) -> None:
        if self.__dict__.get("_is_resizing", False):
            for message in messages:
                self.log_queue.put(self._sanitize_log_message(message))
            return

        inserted = 0
        should_scroll = self._log_is_at_bottom()
        for message in messages:
            text = self._sanitize_log_message(message)
            tag = classify_log_message(text)
            inserted += text.count("\n") + 1
            try:
                self.log_text.insert("end", text + "\n", tag)
            except Exception:  # noqa: BLE001 - fallback for alternate CTkTextbox implementations.
                self.log_text.insert("end", text + "\n")
        self.log_line_count += inserted
        self._trim_log_lines()
        if should_scroll:
            self.log_text.see("end")

    def _log_is_at_bottom(self) -> bool:
        try:
            _first, last = self.log_text.yview()
        except Exception:  # noqa: BLE001 - alternate text widgets may not expose yview.
            return True
        return float(last) >= 0.98

    def _trim_log_lines(self) -> None:
        overflow = self.log_line_count - MAX_LOG_LINES
        if overflow <= 0:
            return
        try:
            self.log_text.delete("1.0", f"{overflow + 1}.0")
            self.log_line_count -= overflow
        except Exception:  # noqa: BLE001 - keep logging functional if trimming is unsupported.
            self.log_line_count = MAX_LOG_LINES

    def _sanitize_log_message(self, message: object) -> str:
        return sanitize_log_message(message, config_data=self.config_data, config=self.config)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (
            self.preview_button,
            self.sync_button,
            self.browse_folder_button,
            self.folder_button,
            self.open_staging_button,
            self.open_config_button,
            self.open_readme_button,
            self.clear_log_button,
            self.copy_log_button,
            self.scan_profiles_button,
            self.test_login_button,
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
        color = {
            STATUS_READY: COLORS["success"],
            STATUS_RUNNING: COLORS["primary"],
            STATUS_DONE: COLORS["success"],
            STATUS_FAILED: COLORS["danger"],
        }.get(value, COLORS["text_muted"])
        if hasattr(self, "status_dot"):
            self.status_dot.configure(text_color=color)

    @staticmethod
    def _set_entry(entry: Any, value: object) -> None:
        previous_state = None
        try:
            previous_state = entry.cget("state")
            if previous_state == "disabled":
                entry.configure(state="normal")
        except Exception:  # noqa: BLE001 - test doubles or alternate widgets may not expose cget.
            previous_state = None
        entry.delete(0, "end")
        entry.insert(0, str(value))
        if previous_state == "disabled":
            entry.configure(state="disabled")


class EagleFolderPickerDialog:
    def __init__(
        self,
        parent: Any,
        *,
        config: AppConfig,
        initial_folder_id: str | None = None,
        on_select: Callable[[dict[str, str]], None],
        log: Callable[[str], None] | None = None,
    ) -> None:
        if ctk is None:
            raise RuntimeError("customtkinter is not installed")
        self.parent = parent
        self.config = config
        self.initial_folder_id = initial_folder_id
        self.on_select = on_select
        self.log = log
        self.folders: list[dict[str, Any]] = []
        self.folder_by_id: dict[str, dict[str, Any]] = {}
        self.children_by_parent: dict[str | None, list[dict[str, Any]]] = {}
        self.selected_folder: dict[str, Any] | None = None
        self.search_after_id: str | None = None
        self.expanded_folder_ids: set[str] = set()
        self.visible_rows: list[dict[str, Any]] = []
        self.hover_row_index: int | None = None

        self.window = ctk.CTkToplevel(parent)
        self.window.title("选择 Eagle 导入位置")
        self.window.configure(fg_color=COLORS["window"])
        center_window(self.window, 760, 620)
        self.window.minsize(620, 460)
        self.window.transient(parent)
        self.window.grid_columnconfigure(0, weight=1)
        self.window.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self.window, text="选择 Eagle 导入位置", text_color=COLORS["text"], font=FONTS["page_title"]).grid(
            row=0, column=0, padx=SPACE["lg"], pady=(SPACE["lg"], SPACE["sm"]), sticky="w"
        )
        self.search_entry = ctk.CTkEntry(
            self.window,
            placeholder_text="搜索文件夹...",
            height=INPUT_HEIGHT,
            **ENTRY_STYLE,
        )
        self.search_entry.grid(row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["md"]), sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._schedule_render)

        self.list_frame = ctk.CTkFrame(
            self.window,
            fg_color=COLORS["card"],
            corner_radius=RADIUS["card"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.list_frame.grid(row=2, column=0, padx=SPACE["lg"], pady=(0, SPACE["md"]), sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.list_frame.grid_rowconfigure(0, weight=1)
        self.tree_canvas = tk.Canvas(
            self.list_frame,
            bg=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["border_soft"],
            bd=0,
            relief="flat",
        )
        self.tree_canvas.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.tree_scrollbar = tk.Scrollbar(
            self.list_frame,
            orient="vertical",
            command=self._tree_yview,
            width=14,
            bg=COLORS["surface_3"],
            troughcolor=COLORS["surface"],
            activebackground=COLORS["selection_hover"],
            highlightthickness=0,
            bd=0,
        )
        self.tree_scrollbar.grid(row=0, column=1, sticky="ns", pady=1)
        self.tree_canvas.configure(yscrollcommand=self.tree_scrollbar.set)
        self.tree_canvas.bind("<Button-1>", self._tree_clicked)
        self.tree_canvas.bind("<Double-Button-1>", self._tree_double_clicked)
        self.tree_canvas.bind("<Motion>", self._tree_motion)
        self.tree_canvas.bind("<Leave>", self._tree_left)
        self.tree_canvas.bind("<MouseWheel>", self._tree_mousewheel)
        self.tree_canvas.bind("<Configure>", lambda _event: self._draw_tree())

        self.message_var = ctk.StringVar(value="正在读取 Eagle 文件夹...")
        ctk.CTkLabel(self.window, textvariable=self.message_var, text_color=COLORS["text_muted"], font=FONTS["body"]).grid(
            row=3, column=0, padx=SPACE["lg"], pady=(0, SPACE["sm"]), sticky="w"
        )

        actions = ctk.CTkFrame(self.window, fg_color="transparent")
        actions.grid(row=4, column=0, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="ew")
        actions.grid_columnconfigure(1, weight=1)
        self.refresh_button = ctk.CTkButton(
            actions,
            text="刷新",
            width=88,
            height=BUTTON_HEIGHT,
            command=self.refresh,
            corner_radius=RADIUS["control"],
            font=FONTS["button"],
            **BUTTON_STYLES["secondary"],
        )
        self.refresh_button.grid(row=0, column=0, padx=(0, SPACE["sm"]), sticky="w")
        self.cancel_button = ctk.CTkButton(
            actions,
            text="取消",
            width=88,
            height=BUTTON_HEIGHT,
            command=self.window.destroy,
            corner_radius=RADIUS["control"],
            font=FONTS["button"],
            **BUTTON_STYLES["secondary"],
        )
        self.cancel_button.grid(row=0, column=2, padx=SPACE["sm"], sticky="e")
        self.select_button = ctk.CTkButton(
            actions,
            text="选择此文件夹",
            width=120,
            height=BUTTON_HEIGHT,
            command=self.confirm_selection,
            corner_radius=RADIUS["control"],
            font=FONTS["button"],
            **BUTTON_STYLES["primary"],
        )
        self.select_button.grid(row=0, column=3, padx=(SPACE["sm"], 0), sticky="e")
        self.select_button.configure(state="disabled")

        self.window.after(50, self.refresh)

    def refresh(self) -> None:
        self.message_var.set("正在读取 Eagle 文件夹...")
        self._clear_tree()
        self.refresh_button.configure(state="disabled")

        def run() -> None:
            try:
                result = services.list_folders(self.config)
            except Exception as exc:  # noqa: BLE001 - dialog must not crash GUI.
                result = {"ok": False, "messages": [str(exc)]}
            self.window.after(0, lambda: self._apply_folder_result(result))

        threading.Thread(target=run, daemon=True).start()

    def _apply_folder_result(self, result: dict[str, Any]) -> None:
        self.refresh_button.configure(state="normal")
        if not result.get("ok"):
            message = folder_picker_error_message(result.get("messages", []))
            self.message_var.set(message)
            if self.log is not None:
                self.log(message)
            return

        self.folders = [folder for folder in result.get("folders", []) if isinstance(folder, dict)]
        self.folder_by_id = {str(folder.get("id") or ""): folder for folder in self.folders if folder.get("id")}
        self.children_by_parent = folder_children_index(self.folders)
        if not self.folders:
            message = "当前 Eagle 资料库没有可用文件夹。"
            self.message_var.set(message)
            if self.log is not None:
                self.log(message)
            return

        self.selected_folder = find_folder_by_id(self.folders, self.initial_folder_id)
        self.select_button.configure(state="normal" if self.selected_folder else "disabled")
        self.message_var.set(f"已读取 {len(self.folders)} 个 Eagle 文件夹。")
        self._render_tree()

    def _schedule_render(self, _event: object | None = None) -> None:
        if self.search_after_id is not None:
            self.window.after_cancel(self.search_after_id)
        self.search_after_id = self.window.after(FOLDER_SEARCH_DEBOUNCE_MS, self._render_tree)

    def _render_tree(self) -> None:
        self.search_after_id = None
        self.visible_rows = folder_picker_rows(
            self.folders,
            self.search_entry.get(),
            expanded_ids=self.expanded_folder_ids,
        )
        if not self.visible_rows:
            self._clear_tree()
            self.message_var.set("没有匹配的 Eagle 文件夹。")
            return
        self._draw_tree()

    def select_folder(self, folder: dict[str, Any]) -> None:
        self.selected_folder = folder
        self.select_button.configure(state="normal")
        self.message_var.set(str(folder.get("path") or folder.get("name") or ""))

    def confirm_folder(self, folder: dict[str, Any]) -> None:
        self.selected_folder = folder
        self.confirm_selection()

    def confirm_selection(self) -> None:
        if self.selected_folder is None:
            self.message_var.set("请先选择一个 Eagle 文件夹。")
            return
        self.on_select(folder_selection_result(self.selected_folder))
        self.window.destroy()

    def _draw_tree(self) -> None:
        self.tree_canvas.delete("all")
        width = max(self.tree_canvas.winfo_width(), 320)
        total_height = max(len(self.visible_rows) * FOLDER_ROW_HEIGHT, self.tree_canvas.winfo_height())
        self.tree_canvas.configure(scrollregion=(0, 0, width, total_height))

        start_index, end_index = self._visible_tree_index_range()
        for index in range(start_index, end_index):
            row = self.visible_rows[index]
            self._draw_tree_row(index, row, width)

    def _visible_tree_index_range(self) -> tuple[int, int]:
        if not self.visible_rows:
            return 0, 0
        top = max(0, int(self.tree_canvas.canvasy(0) // FOLDER_ROW_HEIGHT) - TREE_RENDER_BUFFER_ROWS)
        visible_count = int(self.tree_canvas.winfo_height() // FOLDER_ROW_HEIGHT) + (TREE_RENDER_BUFFER_ROWS * 2) + 2
        bottom = min(len(self.visible_rows), top + visible_count)
        return top, bottom

    def _draw_tree_row(self, index: int, row: dict[str, Any], width: int) -> None:
        folder = row["folder"]
        folder_id = str(folder.get("id") or "")
        y0 = index * FOLDER_ROW_HEIGHT
        y1 = y0 + FOLDER_ROW_HEIGHT
        selected = self.selected_folder is not None and str(self.selected_folder.get("id") or "") == folder_id
        if selected:
            bg = COLORS["selection"]
        elif self.hover_row_index == index:
            bg = COLORS["selection_hover"]
        else:
            bg = COLORS["surface"]
        self.tree_canvas.create_rectangle(0, y0, width, y1, fill=bg, outline="")

        depth = int(row.get("depth") or 0)
        x = 14 + depth * FOLDER_INDENT
        has_children = bool(self.children_by_parent.get(folder_id)) and not row.get("search")
        arrow = folder_row_arrow(folder, expanded_ids=self.expanded_folder_ids, search=bool(row.get("search")), has_children=has_children)
        self.tree_canvas.create_text(
            x + FOLDER_ARROW_WIDTH / 2,
            y0 + FOLDER_ROW_HEIGHT / 2,
            text=arrow,
            fill=COLORS["text_muted"] if has_children else COLORS["text_dim"],
            font=(FONTS["body"][0], 18, "bold"),
            anchor="center",
        )
        color = folder_icon_color(folder.get("icon_color"))
        self.tree_canvas.create_oval(
            x + FOLDER_ARROW_WIDTH + 2,
            y0 + 14,
            x + FOLDER_ARROW_WIDTH + 8,
            y0 + 20,
            fill=color,
            outline="",
        )
        text = format_folder_row_text(row)
        self.tree_canvas.create_text(
            x + FOLDER_ARROW_WIDTH + 16,
            y0 + FOLDER_ROW_HEIGHT / 2,
            text=text,
            fill=COLORS["text"] if selected else COLORS["text_muted"],
            font=FONTS["body"],
            anchor="w",
        )

    def _row_index_from_event(self, event: object) -> int | None:
        canvas_y = self.tree_canvas.canvasy(getattr(event, "y", 0))
        index = int(canvas_y // FOLDER_ROW_HEIGHT)
        if 0 <= index < len(self.visible_rows):
            return index
        return None

    def _tree_clicked(self, event: object) -> None:
        index = self._row_index_from_event(event)
        if index is None:
            return
        row = self.visible_rows[index]
        folder = row["folder"]
        folder_id = str(folder.get("id") or "")
        x = getattr(event, "x", 0)
        depth = int(row.get("depth") or 0)
        arrow_left = 14 + depth * FOLDER_INDENT
        arrow_right = arrow_left + FOLDER_ARROW_WIDTH
        has_children = bool(self.children_by_parent.get(folder_id)) and not row.get("search")
        if has_children and arrow_left <= x <= arrow_right:
            if folder_id in self.expanded_folder_ids:
                self.expanded_folder_ids.remove(folder_id)
            else:
                self.expanded_folder_ids.add(folder_id)
            self._render_tree()
            return
        self.select_folder(folder)
        self._draw_tree()

    def _tree_double_clicked(self, event: object) -> None:
        index = self._row_index_from_event(event)
        if index is None:
            return
        self.confirm_folder(self.visible_rows[index]["folder"])

    def _tree_motion(self, event: object) -> None:
        index = self._row_index_from_event(event)
        if index != self.hover_row_index:
            self.hover_row_index = index
            self._draw_tree()

    def _tree_left(self, _event: object | None = None) -> None:
        if self.hover_row_index is not None:
            self.hover_row_index = None
            self._draw_tree()

    def _tree_mousewheel(self, event: object) -> str:
        delta = getattr(event, "delta", 0)
        if delta:
            self.tree_canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            self._draw_tree()
        return "break"

    def _tree_yview(self, *args: object) -> None:
        self.tree_canvas.yview(*args)
        self._draw_tree()

    def _clear_tree(self) -> None:
        self.visible_rows = []
        self.hover_row_index = None
        self.tree_canvas.delete("all")
        self.tree_canvas.configure(scrollregion=(0, 0, 1, 1))


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
    try:
        write_config_data(data, path)
    except PermissionError as exc:
        raise RuntimeError(
            f"无法在 {path.parent} 创建 config.json。请把程序放到可写目录后再运行。"
        ) from exc
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
    if not data.get("default_eagle_folder_path") and data.get("default_eagle_root_folder"):
        normalized["default_eagle_folder_path"] = data["default_eagle_root_folder"]
    if not normalized.get("default_eagle_root_folder") and normalized.get("default_eagle_folder_path"):
        normalized["default_eagle_root_folder"] = normalized["default_eagle_folder_path"]
    proxy = normalized.get("proxy", {})
    source_proxy = data.get("proxy", {}) if isinstance(data.get("proxy", {}), dict) else {}
    if "mode" not in source_proxy:
        if source_proxy.get("http_proxy") or source_proxy.get("https_proxy"):
            proxy["mode"] = "manual"
        elif "enabled" in source_proxy:
            proxy["mode"] = "manual" if source_proxy.get("enabled") else "none"
        else:
            proxy["mode"] = "auto"
    proxy["enabled"] = proxy.get("mode") != "none"
    return normalized


def default_config_data() -> dict[str, Any]:
    return deepcopy(DEFAULT_CONFIG_DATA)


def get_config_value(data: dict[str, Any], key: str) -> Any:
    if key == "cookies_file":
        return data.get("cookies", {}).get("file") or ""
    if key == STORAGE_PARENT_KEY:
        return data.get(STORAGE_PARENT_KEY, "")
    if key == "staging_dir":
        return data.get("staging_dir", "")
    if key == "archive_db":
        return data.get("archive_db", "")
    if key == "imported_state":
        return data.get("imported_state", "")
    if key == "eagle_api_base":
        return data.get("eagle_api_base", "")
    if key == "default_folder_path":
        return data.get("default_eagle_folder_path") or data.get("default_eagle_root_folder") or DEFAULT_FOLDER_PATH
    if key == "default_folder_id":
        return data.get("default_eagle_folder_id") or ""
    if key == "last_folder_path":
        return data.get("last_eagle_folder_path") or ""
    if key == "last_folder_id":
        return data.get("last_eagle_folder_id") or ""
    if key == "http_proxy":
        return data.get("proxy", {}).get("http_proxy") or ""
    if key == "https_proxy":
        return data.get("proxy", {}).get("https_proxy") or ""
    if key == "proxy_mode":
        return data.get("proxy", {}).get("mode") or ("manual" if data.get("proxy", {}).get("enabled") else "none")
    if key == "detected_proxy":
        return data.get("proxy", {}).get("detected_proxy") or ""
    if key == "max_posts":
        return data.get("download", {}).get("max_posts", -1)
    if key == "sleep_request":
        return data.get("download", {}).get("sleep_request", "8-15")
    raise KeyError(key)


def get_login_form_values(data: dict[str, Any]) -> tuple[str, str, str]:
    cookies = data.get("cookies", {})
    if not cookies.get("enabled", False):
        return LOGIN_NONE, "Chrome", "Default"

    from_browser = str(cookies.get("from_browser") or "").strip()
    if from_browser:
        browser_value, profile = parse_from_browser_value(from_browser)
        return LOGIN_BROWSER, browser_label_from_value(browser_value), profile

    return LOGIN_COOKIE_FILE, "Chrome", "Default"


def apply_login_settings(
    data: dict[str, Any],
    *,
    method: str,
    browser_label: str,
    profile: str,
    cookie_file: str,
) -> dict[str, Any]:
    updated = normalize_config_data(data)
    cookies = updated["cookies"]
    if method == LOGIN_BROWSER:
        cookies["enabled"] = True
        cookies["from_browser"] = build_from_browser_value(browser_label, profile)
        cookies["file"] = ""
    elif method == LOGIN_COOKIE_FILE:
        cookies["enabled"] = True
        cookies["from_browser"] = ""
        cookies["file"] = cookie_file.strip()
    else:
        cookies["enabled"] = False
        cookies["from_browser"] = ""
        cookies["file"] = ""
    return updated


def apply_proxy_settings(
    data: dict[str, Any],
    *,
    mode_label: str,
    http_proxy: str,
    https_proxy: str,
    detected_result: str = "",
) -> dict[str, Any]:
    updated = normalize_config_data(data)
    proxy = updated["proxy"]
    mode = PROXY_MODE_TO_VALUE.get(mode_label, "auto")
    proxy["mode"] = mode
    if mode == "manual":
        proxy["enabled"] = True
        proxy["http_proxy"] = normalize_proxy_url(http_proxy) if http_proxy else ""
        proxy["https_proxy"] = normalize_proxy_url(https_proxy or http_proxy) if (https_proxy or http_proxy) else ""
        proxy["detected_proxy"] = ""
    elif mode == "none":
        proxy["enabled"] = False
        proxy["http_proxy"] = ""
        proxy["https_proxy"] = ""
        proxy["detected_proxy"] = ""
    else:
        proxy["enabled"] = True
        proxy["http_proxy"] = ""
        proxy["https_proxy"] = ""
        prefix = "当前检测结果：已检测到 "
        proxy["detected_proxy"] = detected_result.removeprefix(prefix) if detected_result.startswith(prefix) else ""
    return updated


def get_last_or_default_folder(data: dict[str, Any]) -> dict[str, str]:
    last_path = str(get_config_value(data, "last_folder_path") or "")
    last_id = str(get_config_value(data, "last_folder_id") or "")
    if last_path or last_id:
        return {"folder_path": last_path, "folder_id": last_id}
    return {
        "folder_path": str(get_config_value(data, "default_folder_path") or ""),
        "folder_id": str(get_config_value(data, "default_folder_id") or ""),
    }


def apply_last_eagle_folder(data: dict[str, Any], selection: dict[str, str]) -> dict[str, Any]:
    updated = normalize_config_data(data)
    updated["last_eagle_folder_path"] = str(selection.get("folder_path") or "")
    updated["last_eagle_folder_id"] = str(selection.get("folder_id") or "")
    return updated


def build_storage_paths(parent_dir: str | Path) -> dict[str, Path]:
    parent = Path(parent_dir).expanduser()
    return {
        "staging_dir": parent / STAGING_DIR_NAME,
        "archive_db": parent / CACHE_DIR_NAME / ARCHIVE_DB_NAME,
        "imported_state": parent / CACHE_DIR_NAME / IMPORTED_STATE_NAME,
    }


def apply_storage_parent(data: dict[str, Any], parent_dir: str | Path) -> dict[str, Any]:
    updated = normalize_config_data(data)
    parent = str(Path(parent_dir).expanduser())
    paths = build_storage_paths(parent)
    updated[STORAGE_PARENT_KEY] = parent
    updated["staging_dir"] = str(paths["staging_dir"])
    updated["archive_db"] = str(paths["archive_db"])
    updated["imported_state"] = str(paths["imported_state"])
    return updated


def build_from_browser_value(browser_label: str, profile: str) -> str:
    browser = BROWSER_VALUES.get(browser_label, browser_label.lower())
    profile_text = profile.strip() or "Default"
    return f"{browser}:{profile_text}"


def parse_from_browser_value(value: str) -> tuple[str, str]:
    text = value.strip()
    browser = text
    profile = "Default"
    if ":" in text:
        browser, profile = text.split(":", 1)
    if "/" in browser:
        browser = browser.split("/", 1)[0]
    return browser.lower(), profile or "Default"


def browser_label_from_value(value: str) -> str:
    normalized = value.lower()
    for label, browser_value in BROWSER_VALUES.items():
        if browser_value == normalized:
            return label
    return "Chrome"


def classify_log_message(message: str) -> str:
    text = message.lower()
    if message.startswith("错误") or " error" in text or "[error]" in text:
        return "error"
    if message.startswith("警告") or message.startswith("提示") or "warning" in text or "[warning]" in text:
        return "warning"
    if message.startswith("正常") or message.startswith("登录测试完成") or "成功" in message:
        return "ok"
    return "muted"


def folder_picker_rows(
    folders: list[dict[str, Any]],
    query: str = "",
    *,
    expanded_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    text = query.strip().lower()
    expanded = expanded_ids or set()
    children_by_parent = folder_children_index(folders)
    rows: list[dict[str, Any]] = []
    if not text:
        def add_visible(parent_id: str | None, depth: int) -> None:
            for folder in children_by_parent.get(parent_id, []):
                rows.append({"folder": folder, "depth": depth, "search": False})
                folder_id = str(folder.get("id") or "")
                if folder_id in expanded:
                    add_visible(folder_id, depth + 1)

        add_visible(None, 0)
        return rows

    for folder in folders:
        path = str(folder.get("path") or folder.get("name") or "")
        name = str(folder.get("name") or "")
        if text not in name.lower() and text not in path.lower():
            continue
        rows.append(
            {
                "folder": folder,
                "depth": 0,
                "search": True,
            }
        )
    return rows


def format_folder_row_text(row: dict[str, Any]) -> str:
    folder = row["folder"]
    path = str(folder.get("path") or folder.get("name") or "")
    count = _safe_int(folder.get("descendant_image_count") or folder.get("image_count") or 0)
    suffix = f"  ({count})" if count else ""
    if row.get("search"):
        return f"{FOLDER_DISPLAY_ICON} {path}{suffix}".strip()
    return f"{FOLDER_DISPLAY_ICON} {folder.get('name') or path}{suffix}".strip()


def folder_row_arrow(
    folder: dict[str, Any],
    *,
    expanded_ids: set[str],
    search: bool,
    has_children: bool,
) -> str:
    if search or not has_children:
        return ""
    return "▾" if str(folder.get("id") or "") in expanded_ids else "▸"


def folder_children_index(folders: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    folder_ids = {str(folder.get("id") or "") for folder in folders if folder.get("id")}
    children_by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for folder in folders:
        parent_id = folder.get("parent_id")
        resolved_parent_id = str(parent_id) if parent_id and str(parent_id) in folder_ids else None
        children_by_parent.setdefault(resolved_parent_id, []).append(folder)
    return children_by_parent


def folder_selection_result(folder: dict[str, Any]) -> dict[str, str]:
    return {
        "folder_id": str(folder.get("id") or ""),
        "folder_path": str(folder.get("path") or folder.get("name") or ""),
    }


def find_folder_by_id(folders: list[dict[str, Any]], folder_id: str | None) -> dict[str, Any] | None:
    if not folder_id:
        return None
    for folder in folders:
        if str(folder.get("id") or "") == folder_id:
            return folder
    return None


def folder_picker_error_message(messages: object) -> str:
    if isinstance(messages, (list, tuple)):
        detail = "; ".join(str(message) for message in messages if message)
    else:
        detail = str(messages or "")
    lowered = detail.lower()
    if any(marker in lowered for marker in ("connection", "refused", "not available", "failed to establish")):
        return "无法读取 Eagle 文件夹，请确认 Eagle 已打开并且本地 API 地址正确。"
    if not detail:
        return "读取 Eagle 文件夹失败。"
    return f"读取 Eagle 文件夹失败：{detail}"


def folder_icon_color(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("#") and len(text) in {4, 7, 9}:
        return text
    return COLORS["primary"]


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def today_iso() -> str:
    return date.today().isoformat()


def author_date_range(anchor_date: str, range_label: str, amount: int = 1) -> tuple[str, str]:
    text = str(anchor_date or "").strip() or today_iso()
    try:
        end_date = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("时间基准日期必须是 YYYY-MM-DD 格式。") from exc
    if amount <= 0:
        raise ValueError("时间范围数量必须大于 0。")

    if range_label == DATE_RANGE_WEEK:
        start_date = end_date - timedelta(days=(amount * 7) - 1)
    elif range_label == DATE_RANGE_MONTH:
        start_date = _shift_months(end_date, -amount) + timedelta(days=1)
    elif range_label == DATE_RANGE_YEAR:
        start_date = _shift_months(end_date, -(amount * 12)) + timedelta(days=1)
    else:
        start_date = end_date - timedelta(days=amount - 1)

    return start_date.isoformat(), (end_date + timedelta(days=1)).isoformat()


def _shift_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day


def scan_browser_profiles(
    browser_label: str,
    *,
    local_appdata: str | Path | None = None,
    appdata: str | Path | None = None,
) -> list[str]:
    browser_value = BROWSER_VALUES.get(browser_label, browser_label.lower())
    if browser_value in {"chrome", "edge"}:
        base = _chromium_user_data_dir(browser_value, local_appdata=local_appdata)
        return _scan_chromium_profiles(base)
    if browser_value == "firefox":
        base = Path(appdata or os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        return _sort_profiles([path.name for path in base.iterdir() if path.is_dir()]) if base.exists() else []
    return []


def cookie_help_text() -> str:
    return (
        "如何获取 cookies.txt？\n\n"
        "1. 在浏览器中登录 Instagram。\n"
        "2. 使用 Get cookies.txt LOCALLY 插件导出 instagram.com 的 cookies。\n"
        f"   下载地址：{COOKIE_HELP_URL}\n"
        "3. 点击插件的 “Export As” 保存为 instagram-cookies.txt。\n"
        "4. 回到本工具，选择该文件。\n"
        "5. 不要把 cookies.txt 分享给任何人。\n\n"
        "注意：cookies.txt 相当于临时登录凭证，请勿分享。"
    )


def open_cookie_help_url() -> None:
    webbrowser.open(COOKIE_HELP_URL)


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


def run_instagram_login_check(config: AppConfig, url: str = DEFAULT_LOGIN_TEST_URL) -> list[str]:
    messages: list[str] = []
    try:
        command = build_login_check_command(config, url)
    except Exception as exc:  # noqa: BLE001 - user-facing diagnostics.
        return [sanitize_log_message(f"错误：无法生成登录测试命令：{exc}", config=config)]

    messages.append(f"登录测试命令：{format_command_for_log(command)}")
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            env=build_subprocess_env(config),
        )
    except Exception as exc:  # noqa: BLE001 - user-facing diagnostics.
        return [
            *[sanitize_log_message(message, config=config) for message in messages],
            sanitize_log_message(f"错误：登录测试失败：{exc}", config=config),
        ]

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    if result.returncode == 0:
        messages.append("登录测试完成：gallery-dl 可以使用当前登录配置。")
    else:
        detail = stderr or stdout or f"gallery-dl 退出码 {result.returncode}"
        messages.append(f"警告：登录测试未通过：{detail}")
        if should_show_login_failure_hint(detail):
            messages.append(FRIENDLY_LOGIN_FAILURE_HINT)
    return [sanitize_log_message(message, config=config) for message in messages]


def build_login_check_command(config: AppConfig, url: str) -> list[str]:
    command = resolve_gallery_dl_command(config)
    if not command:
        raise RuntimeError("未找到 gallery-dl，无法测试 Instagram 登录状态。")
    command.append("--config-ignore")
    command.extend(build_cookie_args(config))
    command.extend(["--simulate", "--range", "1-1", url or DEFAULT_LOGIN_TEST_URL])
    return command


def should_show_login_failure_hint(text: str) -> bool:
    lowered = text.lower()
    if "accounts/login" in lowered or "redirect to login" in lowered or "permission denied" in lowered:
        return True
    return is_browser_cookie_error(text) or (
        ("cookies" in lowered or "cookie" in lowered)
        and (
            "permission denied" in lowered
            or "failed to decrypt" in lowered
            or "unable to find" in lowered
            or "locked" in lowered
            or "dpapi" in lowered
            or "nonetype" in lowered
            or "noneType".lower() in lowered
        )
    )


def _chromium_user_data_dir(browser_value: str, *, local_appdata: str | Path | None) -> Path:
    root = Path(local_appdata or os.environ.get("LOCALAPPDATA", ""))
    if browser_value == "edge":
        return root / "Microsoft" / "Edge" / "User Data"
    return root / "Google" / "Chrome" / "User Data"


def _scan_chromium_profiles(base: Path) -> list[str]:
    if not base.exists():
        return []
    profiles = []
    for path in base.iterdir():
        if not path.is_dir():
            continue
        if (path / "Network" / "Cookies").exists() or (path / "Cookies").exists():
            profiles.append(path.name)
    return _sort_profiles(profiles)


def _sort_profiles(profiles: list[str]) -> list[str]:
    return sorted(dict.fromkeys(profiles), key=lambda name: (name != "Default", name.lower()))


def run_startup_checks(config: AppConfig) -> list[str]:
    messages = ["启动检查："]
    messages.append(f"当前运行环境：{'已打包运行' if is_frozen() else '开发环境'}")

    if config.eagle_api_base:
        try:
            EagleClient(config.eagle_api_base).check_app_available()
            messages.append("正常：Eagle 本地 API 可以连接。")
        except Exception as exc:  # noqa: BLE001 - startup diagnostics should never crash GUI.
            messages.append(f"警告：Eagle 本地 API 暂时无法连接：{exc}")
    else:
        messages.append("警告：Eagle 本地 API 地址为空。")

    if not config.cookies.enabled:
        messages.append("提示：当前使用不登录模式，仅能下载公开内容。")
    elif config.cookies.from_browser:
        messages.append("提示：将自动从浏览器读取 Instagram 登录状态，读取前请关闭对应浏览器。")
    elif config.cookies.file is None:
        messages.append("警告：Instagram 登录 Cookie 文件未设置，部分内容可能需要登录。")
    elif config.cookies.file.exists():
        messages.append("正常：Instagram 登录 Cookie 文件已找到：<hidden>")
    else:
        messages.append("警告：Instagram 登录 Cookie 文件不存在：<hidden>")

    messages.append(f"当前代理模式：{proxy_mode_label(getattr(config.proxy, 'mode', 'auto'))}")
    gallery_ok, gallery_message = check_gallery_dl_available(config)
    messages.append(gallery_message if gallery_ok else f"警告：{gallery_message}")
    ytdlp_ok, ytdlp_message = check_ytdlp_available(config)
    messages.append(ytdlp_message if ytdlp_ok else f"提示：{ytdlp_message}")
    return [sanitize_log_message(message, config=config) for message in messages]


def check_gallery_dl_available(config: AppConfig | str) -> tuple[bool, str]:
    if isinstance(config, str):
        command = [*split_command(config), "--version"]
    else:
        command = resolve_gallery_dl_command(config)
        if not command:
            return False, "未找到 gallery-dl，无法下载。请确认发布包完整。"
        command = [*command, "--version"]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 - startup diagnostics should stay non-fatal.
        return False, f"gallery-dl 不可用：{exc}"

    if result.returncode == 0:
        version = (result.stdout or result.stderr or "").strip()
        suffix = f" ({version})" if version else ""
        if len(command) >= 2 and Path(command[0]).name.lower() == GALLERY_DL_EXE_NAME:
            return True, f"正常：已找到内置 gallery-dl.exe{suffix}。"
        if FROZEN_GALLERY_DL_MODULE_ARG in command:
            return True, f"正常：已内置 gallery-dl Python 模块{suffix}。"
        return True, f"正常：开发环境 gallery-dl Python 模块可用{suffix}。"
    stderr = (result.stderr or result.stdout or "").strip()
    detail = f": {stderr}" if stderr else ""
    return False, f"未找到 gallery-dl，检查失败，退出码 {result.returncode}{detail}"


def check_ytdlp_available(config: AppConfig) -> tuple[bool, str]:
    command = resolve_ytdlp_command(config)
    if not command:
        return False, "未找到 yt-dlp，部分视频可能使用备用下载方式。"
    if len(command) == 1 and Path(command[0]).name.lower() == YT_DLP_EXE_NAME:
        return True, "正常：已找到 yt-dlp.exe。"
    try:
        result = subprocess.run(
            [*command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False, "未找到 yt-dlp，部分视频可能使用备用下载方式。"
    if result.returncode == 0:
        return True, "正常：yt-dlp Python 模块可用。"
    return False, "未找到 yt-dlp，部分视频可能使用备用下载方式。"


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
        from_browser = config_data.get("cookies", {}).get("from_browser")
        if from_browser:
            candidates.add(str(from_browser))
            _browser, profile = parse_from_browser_value(str(from_browser))
            if profile != "Default":
                candidates.add(profile)
    if config and config.cookies.file:
        candidates.update(_path_variants(str(config.cookies.file)))
    if config and config.cookies.from_browser:
        candidates.add(config.cookies.from_browser)
        _browser, profile = parse_from_browser_value(config.cookies.from_browser)
        if profile != "Default":
            candidates.add(profile)
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

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = InsEagleSyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
