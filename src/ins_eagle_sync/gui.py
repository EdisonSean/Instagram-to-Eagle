from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import traceback
import webbrowser
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - runtime dependency hint for GUI users.
    ctk = None  # type: ignore[assignment]

from . import services
from .config import AppConfig, load_config, parse_config
from .eagle_client import EagleClient
from .gallerydl_runner import build_cookie_args, build_subprocess_env, format_command_for_log, is_browser_cookie_error
from .ui_theme import APP_TITLE, BUTTON_HEIGHT, COLORS, FONTS, INPUT_HEIGHT, RADIUS, SPACE
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

DEFAULT_CONFIG_DATA: dict[str, Any] = {
    "gallery_dl_executable": "py -m gallery_dl",
    STORAGE_PARENT_KEY: "",
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
        self.title(APP_TITLE)
        self.geometry("1500x900")
        self.minsize(1160, 740)
        self.configure(fg_color=COLORS["window"])

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_panel_visible = True
        self.worker: threading.Thread | None = None
        self.setting_entries: dict[str, Any] = {}
        self.status_var = ctk.StringVar(value=STATUS_READY)
        self.storage_preview_vars = {
            "staging_dir": ctk.StringVar(value="未设置"),
            "archive_db": ctk.StringVar(value="未设置"),
            "imported_state": ctk.StringVar(value="未设置"),
        }
        self.config_path = ensure_config_file(DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH)
        self.config_data = load_config_data(self.config_path)
        self.config = self._load_config()

        self._build_layout()
        self._set_default_values()
        self.after(100, self._drain_log_queue)
        self.after(250, self.startup_checks)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.main_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.main_panel.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 12))
        self.main_panel.grid_columnconfigure(0, weight=1)
        self.main_panel.grid_rowconfigure(0, weight=1)

        self.sync_tab = ctk.CTkScrollableFrame(
            self.main_panel,
            fg_color=COLORS["surface"],
            scrollbar_button_color=COLORS["surface_3"],
            scrollbar_button_hover_color=COLORS["primary"],
            corner_radius=RADIUS["card"],
        )
        self.settings_tab = ctk.CTkScrollableFrame(
            self.main_panel,
            fg_color=COLORS["surface"],
            scrollbar_button_color=COLORS["surface_3"],
            scrollbar_button_hover_color=COLORS["primary"],
            corner_radius=RADIUS["card"],
        )
        for frame in (self.sync_tab, self.settings_tab):
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)

        self._build_sync_tab(self.sync_tab)
        self._build_settings_tab(self.settings_tab)
        self._show_main_tab(SYNC_TAB_NAME)
        self._build_log_panel()

        status_bar = ctk.CTkFrame(self, corner_radius=0)
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))
        status_bar.grid_columnconfigure(2, weight=1)
        status_bar.configure(fg_color=COLORS["surface"], border_width=1, border_color=COLORS["border"])
        ctk.CTkLabel(status_bar, text="状态：", text_color=COLORS["text_muted"], font=FONTS["body"]).grid(
            row=0, column=0, padx=(16, 4), pady=8, sticky="w"
        )
        ctk.CTkLabel(status_bar, textvariable=self.status_var, text_color=COLORS["text"], font=FONTS["body"]).grid(
            row=0, column=1, padx=(0, 10), pady=8, sticky="w"
        )
        self.status_dot = ctk.CTkLabel(status_bar, text="●", text_color=COLORS["success"], font=(FONTS["body"][0], 14))
        self.status_dot.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="w")
        self.toggle_log_button = self._button(status_bar, "隐藏日志", self.toggle_log_panel, kind="ghost", width=112)
        self.toggle_log_button.grid(row=0, column=3, padx=12, pady=6, sticky="e")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=64)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=1)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=20, pady=12)
        ctk.CTkLabel(
            brand,
            text="✓",
            width=24,
            height=24,
            fg_color=COLORS["primary"],
            corner_radius=12,
            text_color=COLORS["text"],
            font=(FONTS["button"][0], 13, "bold"),
        ).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(brand, text=APP_TITLE, text_color=COLORS["text"], font=(FONTS["title"][0], 17, "bold")).grid(
            row=0, column=1
        )

        self.nav_tabs = ctk.CTkSegmentedButton(
            header,
            values=[SYNC_TAB_NAME, SETTINGS_TAB_NAME],
            command=self._show_main_tab,
            height=38,
            corner_radius=RADIUS["pill"],
            fg_color=COLORS["surface_2"],
            selected_color=COLORS["primary"],
            selected_hover_color=COLORS["primary_hover"],
            unselected_color=COLORS["surface_2"],
            unselected_hover_color=COLORS["surface_3"],
            text_color=COLORS["text"],
            font=FONTS["button"],
        )
        self.nav_tabs.grid(row=0, column=1, pady=12)
        self.nav_tabs.set(SYNC_TAB_NAME)

    def _show_main_tab(self, value: str) -> None:
        if value == SETTINGS_TAB_NAME:
            self.sync_tab.grid_remove()
            self.settings_tab.grid()
        else:
            self.settings_tab.grid_remove()
            self.sync_tab.grid()

    def _button(
        self,
        parent: Any,
        text: str,
        command: Callable[[], None],
        *,
        kind: str = "secondary",
        width: int = 120,
    ) -> Any:
        if kind == "primary":
            return ctk.CTkButton(
                parent,
                text=text,
                command=command,
                width=width,
                height=BUTTON_HEIGHT,
                fg_color=COLORS["primary"],
                hover_color=COLORS["primary_hover"],
                text_color=COLORS["text"],
                font=FONTS["button"],
                corner_radius=RADIUS["control"],
            )
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=BUTTON_HEIGHT,
            fg_color="transparent",
            hover_color=COLORS["surface_3"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=FONTS["button"],
            corner_radius=RADIUS["control"],
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
            row=0, column=0, padx=(SPACE["lg"], 6), pady=(SPACE["lg"], SPACE["sm"]), sticky="w"
        )
        ctk.CTkLabel(card, text=title, text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=0, padx=(44, SPACE["lg"]), pady=(SPACE["lg"], SPACE["sm"]), sticky="w"
        )
        return card

    def _entry(self, parent: Any, *, placeholder: str = "", width: int | None = None) -> Any:
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            height=INPUT_HEIGHT,
            width=width or 120,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["text_dim"],
            corner_radius=RADIUS["control"],
            font=FONTS["body"],
        )

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
            corner_radius=RADIUS["card"],
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.log_panel.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 12))
        self.log_panel.grid_columnconfigure(0, weight=1)
        self.log_panel.grid_rowconfigure(1, weight=1)

        log_tools = ctk.CTkFrame(self.log_panel, corner_radius=0, fg_color="transparent")
        log_tools.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        log_tools.grid_columnconfigure(5, weight=1)
        ctk.CTkLabel(log_tools, text="▤", text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=0, padx=(0, 8), pady=6, sticky="w"
        )
        ctk.CTkLabel(log_tools, text=LOG_PANEL_TITLE, text_color=COLORS["text"], font=FONTS["section"]).grid(
            row=0, column=1, padx=(0, 12), pady=6, sticky="w"
        )
        self.clear_log_button = self._button(log_tools, "清空", self.clear_log, kind="ghost", width=68)
        self.clear_log_button.grid(row=0, column=2, padx=4, pady=6)
        self.copy_log_button = self._button(log_tools, "复制", self.copy_log, kind="ghost", width=68)
        self.copy_log_button.grid(row=0, column=3, padx=4, pady=6)
        self.close_log_button = self._button(log_tools, "关闭", self.toggle_log_panel, kind="ghost", width=68)
        self.close_log_button.grid(row=0, column=4, padx=4, pady=6)

        self.log_text = ctk.CTkTextbox(
            self.log_panel,
            wrap="word",
            width=420,
            fg_color="#07111d",
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=RADIUS["control"],
            text_color=COLORS["text"],
            font=FONTS["mono"],
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self._configure_log_tags()

    def _build_sync_tab(self, parent: Any) -> None:
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(parent, text="Instagram → Eagle 同步工具", text_color=COLORS["text"], font=FONTS["page_title"]).grid(
            row=0, column=0, padx=SPACE["lg"], pady=(SPACE["xl"], SPACE["lg"]), sticky="w"
        )

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
            height=38,
            fg_color=COLORS["surface_2"],
            selected_color=COLORS["primary"],
            selected_hover_color=COLORS["primary_hover"],
            unselected_color=COLORS["surface_2"],
            unselected_hover_color=COLORS["surface_3"],
            text_color=COLORS["text"],
            font=FONTS["button"],
        )
        self.mode.grid(row=3, column=1, padx=(0, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="ew")

        ctk.CTkLabel(source, text="最多同步帖子数", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=3, column=2, padx=(0, SPACE["sm"]), pady=(0, SPACE["lg"]), sticky="e"
        )
        self.max_posts_entry = self._entry(source, width=112)
        self.max_posts_entry.grid(row=3, column=3, padx=(0, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="e")

        destination = self._card(parent, 2, "2. 导入位置", "▱", columns=3)
        destination.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(destination, text="Eagle 导入位置", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="w"
        )
        self.folder_path_entry = self._entry(destination, placeholder="例如：Instagram/quinn.xyz")
        self.folder_path_entry.grid(row=1, column=1, padx=(0, SPACE["sm"]), pady=(0, SPACE["lg"]), sticky="ew")
        self.browse_folder_button = self._button(destination, "浏览", self.ensure_folder, kind="secondary", width=84)
        self.browse_folder_button.grid(row=1, column=2, padx=(0, SPACE["lg"]), pady=(0, SPACE["lg"]))

        self.verify_var = ctk.BooleanVar(value=True)
        self.ignore_archive_var = ctk.BooleanVar(value=False)
        self.force_var = ctk.BooleanVar(value=False)
        self.dry_run_var = ctk.BooleanVar(value=False)
        self.show_annotation_var = ctk.BooleanVar(value=False)

        common = self._card(parent, 3, "3. 常用选项", "⚙", columns=2)
        common.grid_columnconfigure(0, weight=1)
        common.grid_columnconfigure(1, weight=1)
        ctk.CTkCheckBox(common, text="同步前检查 Eagle 中是否已存在", variable=self.verify_var).grid(
            row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(common, text="避免重复导入，删除后可重新补导入。", text_color="gray").grid(
            row=2, column=0, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )
        ctk.CTkCheckBox(common, text="仅预览，不实际导入", variable=self.dry_run_var).grid(
            row=1, column=1, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(common, text="只显示将要执行的内容。", text_color="gray").grid(
            row=2, column=1, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )

        advanced = self._card(parent, 4, "4. 高级选项", "☷", columns=3)
        for column in range(3):
            advanced.grid_columnconfigure(column, weight=1)
        ctk.CTkCheckBox(advanced, text="忽略下载记录，重新下载", variable=self.ignore_archive_var).grid(
            row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(advanced, text="即使以前下载过，也重新下载。", text_color="gray").grid(
            row=2, column=0, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )
        ctk.CTkCheckBox(advanced, text="强制重新导入", variable=self.force_var).grid(
            row=1, column=1, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(advanced, text="忽略已导入记录，可能产生重复素材。", text_color="gray").grid(
            row=2, column=1, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )
        ctk.CTkCheckBox(advanced, text="显示详细注释", variable=self.show_annotation_var).grid(
            row=1, column=2, padx=SPACE["lg"], pady=(0, SPACE["xs"]), sticky="w"
        )
        ctk.CTkLabel(advanced, text="在日志中显示将写入 Eagle 的完整注释。", text_color="gray").grid(
            row=2, column=2, padx=(44, SPACE["lg"]), pady=(0, SPACE["lg"]), sticky="w"
        )

        actions = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=RADIUS["card"])
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
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(parent, text="设置中心", text_color=COLORS["text"], font=FONTS["page_title"]).grid(
            row=0, column=0, padx=SPACE["lg"], pady=(SPACE["xl"], 4), sticky="w"
        )
        ctk.CTkLabel(
            parent,
            text="管理登录方式、存储路径、网络连接及应用行为设置。",
            text_color=COLORS["text_muted"],
            font=FONTS["body"],
        ).grid(row=1, column=0, padx=SPACE["lg"], pady=(0, SPACE["lg"]), sticky="w")

        login_card = self._card(parent, 2, "1. Instagram 登录方式", "♙", columns=3)
        login_card.grid_columnconfigure(0, weight=1)
        login_card.grid_columnconfigure(1, weight=1)
        login_card.grid_columnconfigure(2, weight=1)
        self.login_method = ctk.CTkSegmentedButton(
            login_card,
            values=[LOGIN_COOKIE_FILE, LOGIN_BROWSER, LOGIN_NONE],
            command=self._login_method_changed,
            height=42,
            fg_color=COLORS["surface_2"],
            selected_color=COLORS["primary"],
            selected_hover_color=COLORS["primary_hover"],
            unselected_color=COLORS["surface_2"],
            unselected_hover_color=COLORS["surface_3"],
            text_color=COLORS["text"],
            font=FONTS["button"],
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

        self.browser_login_frame = ctk.CTkFrame(login_card, corner_radius=RADIUS["control"], fg_color=COLORS["surface_2"])
        self.browser_login_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=SPACE["lg"], pady=(0, SPACE["md"]))
        self.browser_login_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.browser_login_frame, text="浏览器选择", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=0, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=SPACE["md"], sticky="w"
        )
        self.browser_choice = ctk.CTkSegmentedButton(
            self.browser_login_frame,
            values=list(BROWSER_LABELS),
            command=self._browser_changed,
        )
        self.browser_choice.grid(row=0, column=1, padx=(0, SPACE["md"]), pady=SPACE["md"], sticky="w")
        ctk.CTkLabel(self.browser_login_frame, text="Profile", text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=1, column=0, padx=(SPACE["md"], SPACE["sm"]), pady=(0, SPACE["md"]), sticky="w"
        )
        self.browser_profile_entry = ctk.CTkComboBox(
            self.browser_login_frame,
            values=["Default"],
            height=INPUT_HEIGHT,
            fg_color=COLORS["input"],
            button_color=COLORS["surface_3"],
            button_hover_color=COLORS["primary"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            corner_radius=RADIUS["control"],
            font=FONTS["body"],
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

        self.cookie_file_frame = ctk.CTkFrame(login_card, corner_radius=RADIUS["control"], fg_color=COLORS["surface_2"])
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
        for column in range(4):
            connect_card.grid_columnconfigure(column, weight=1)
        self._add_compact_field(connect_card, 1, 0, "Eagle 本地 API 地址", "eagle_api_base")
        self._add_compact_field(connect_card, 1, 2, "HTTPS 代理", "https_proxy")
        self._add_compact_field(connect_card, 2, 0, "默认 Eagle 导入位置", "default_folder_path")
        self._add_compact_field(connect_card, 2, 2, "默认最多同步帖子数", "max_posts")
        self._add_compact_field(connect_card, 3, 0, "HTTP 代理", "http_proxy")
        self._add_compact_field(connect_card, 3, 2, "请求间隔", "sleep_request")

        actions = ctk.CTkFrame(connect_card, corner_radius=0, fg_color="transparent")
        actions.grid(row=4, column=0, columnspan=4, sticky="ew", padx=SPACE["lg"], pady=(SPACE["md"], SPACE["lg"]))
        self.save_settings_button = self._button(actions, "保存设置", self.save_settings, kind="primary", width=180)
        self.save_settings_button.grid(row=0, column=0, padx=(0, SPACE["sm"]), pady=0, sticky="w")
        self.reload_settings_button = self._button(actions, "重新加载", self.reload_settings, width=140)
        self.reload_settings_button.grid(row=0, column=1, padx=SPACE["sm"], pady=0, sticky="w")

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

    def _add_compact_field(self, parent: Any, row: int, column: int, label: str, key: str) -> None:
        ctk.CTkLabel(parent, text=label, text_color=COLORS["text"], font=FONTS["label"]).grid(
            row=row, column=column, padx=(SPACE["lg"], SPACE["sm"]), pady=SPACE["sm"], sticky="w"
        )
        entry = self._entry(parent)
        entry.grid(row=row, column=column + 1, padx=(0, SPACE["lg"]), pady=SPACE["sm"], sticky="ew")
        self.setting_entries[key] = entry

    def _add_storage_preview(self, parent: Any, row: int) -> None:
        frame = ctk.CTkFrame(parent, corner_radius=RADIUS["control"], fg_color=COLORS["surface_2"])
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
            tile = ctk.CTkFrame(frame, corner_radius=RADIUS["control"], fg_color=COLORS["input"])
            tile.grid(row=1, column=index, padx=SPACE["sm"], pady=(0, SPACE["md"]), sticky="nsew")
            ctk.CTkLabel(tile, text=label, text_color=COLORS["text"], font=FONTS["label"]).grid(
                row=0, column=0, padx=SPACE["md"], pady=(SPACE["sm"], 2), sticky="w"
            )
            ctk.CTkLabel(tile, textvariable=self.storage_preview_vars[key], text_color=COLORS["text_muted"], font=FONTS["small"]).grid(
                row=1, column=0, padx=SPACE["md"], pady=(0, SPACE["sm"]), sticky="w"
            )

    def _set_default_values(self) -> None:
        self.mode.set(MODE_POST)
        self._set_entry(self.folder_path_entry, get_config_value(self.config_data, "default_folder_path"))
        self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
        self._populate_settings_form()
        self._sync_mode_changed(MODE_POST)

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

    def save_settings(self) -> None:
        try:
            data = self._collect_settings_data(require_storage_parent=True)
            if data is None:
                return
            write_config_data(data, DEFAULT_CONFIG_PATH)
            self.config_path = Path(DEFAULT_CONFIG_PATH)
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            self._set_entry(self.folder_path_entry, get_config_value(self.config_data, "default_folder_path"))
            self._set_entry(self.max_posts_entry, str(get_config_value(self.config_data, "max_posts")))
            self._sync_mode_changed()
            self._append_log("设置已保存到 config.json。")
            self._warn_about_cookies()
        except Exception as exc:  # noqa: BLE001 - user-facing GUI error.
            self._append_log(f"错误：保存设置失败：{exc}")

    def reload_settings(self) -> None:
        try:
            self.config_path = ensure_config_file(DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH)
            self.config_data = load_config_data(self.config_path)
            self.config = self._load_config()
            self._populate_settings_form()
            self._set_entry(self.folder_path_entry, get_config_value(self.config_data, "default_folder_path"))
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
        if max_posts <= 0:
            self._append_log("错误：默认最多同步帖子数必须大于 0。")
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
        data["proxy"]["enabled"] = bool(http_proxy or https_proxy)
        data["proxy"]["http_proxy"] = http_proxy
        data["proxy"]["https_proxy"] = https_proxy
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
        messagebox.showinfo(
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
            write_config_data(data, DEFAULT_CONFIG_PATH)
            self.config_path = Path(DEFAULT_CONFIG_PATH)
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
        self.max_posts_entry.configure(state="normal" if mode == MODE_AUTHOR else "disabled")

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
        window.geometry("680x420")
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)
        text = ctk.CTkTextbox(window, wrap="word")
        text.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        text.insert("end", cookie_help_text())
        text.configure(state="disabled")
        actions = ctk.CTkFrame(window, corner_radius=0)
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        ctk.CTkButton(actions, text="打开插件下载页", command=open_cookie_help_url).grid(
            row=0, column=0, padx=(0, 8), pady=8
        )
        ctk.CTkButton(actions, text="关闭", command=window.destroy).grid(row=0, column=1, padx=8, pady=8)

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
            return {
                "ok": not any(message.startswith("警告：") or message.startswith("错误：") for message in messages),
                "messages": messages,
            }

        self._start_worker("测试 Instagram 登录状态", task)

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
        readme_path = Path("README.md").resolve()
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
        max_posts = self._read_max_posts() if mode == MODE_AUTHOR else None
        if max_posts is False:
            return

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
            self._append_log("错误：最多同步帖子数必须是数字。")
            return False
        if value <= 0:
            self._append_log("错误：最多同步帖子数必须大于 0。")
            return False
        return value

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
        text = self._sanitize_log_message(message)
        tag = classify_log_message(text)
        try:
            self.log_text.insert("end", text + "\n", tag)
        except Exception:  # noqa: BLE001 - fallback for alternate CTkTextbox implementations.
            self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

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
    command = shlex.split(config.gallery_dl_executable)
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

    gallery_ok, gallery_message = check_gallery_dl_available(config.gallery_dl_executable)
    messages.append(gallery_message if gallery_ok else f"警告：{gallery_message}")
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
        return False, f"gallery-dl 不可用：{exc}"

    if result.returncode == 0:
        version = (result.stdout or result.stderr or "").strip()
        suffix = f" ({version})" if version else ""
        return True, f"正常：gallery-dl 可用{suffix}。"
    stderr = (result.stderr or result.stdout or "").strip()
    detail = f": {stderr}" if stderr else ""
    return False, f"gallery-dl 检查失败，退出码 {result.returncode}{detail}"


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
    ctk.set_default_color_theme("blue")
    app = InsEagleSyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
