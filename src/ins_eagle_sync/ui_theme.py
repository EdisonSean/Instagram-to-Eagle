from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from .runtime import get_resource_path


APP_TITLE = "Instagram to Eagle"
FONT_FAMILY = ".PingFang-SC-Regular"
FONT_RESOURCE_RELATIVE_PATH = Path("assets") / "fonts" / "pingfang-sc-regular.ttf"

COLORS = {
    "window": "#18191B",
    "surface": "#1E1F22",
    "surface_2": "#222326",
    "surface_3": "#2A2B2F",
    "card": "#222326",
    "card_hover": "#2B2C30",
    "sidebar": "#202124",
    "log": "#141518",
    "border": "#34363A",
    "border_soft": "#2B2D31",
    "border_focus": "#2F80ED",
    "primary": "#2F80ED",
    "primary_hover": "#3A8CFF",
    "primary_soft": "#1F3A5F",
    "selection": "#2E3E55",
    "selection_hover": "#33363B",
    "text": "#F1F2F4",
    "text_muted": "#A5A8AE",
    "text_dim": "#737780",
    "input": "#1A1B1E",
    "success": "#5CBF7A",
    "warning": "#DDB86A",
    "danger": "#E06C75",
    "danger_hover": "#C85B63",
}

FONTS = {
    "title": (FONT_FAMILY, 24, "bold"),
    "page_title": (FONT_FAMILY, 24, "bold"),
    "section": (FONT_FAMILY, 20, "bold"),
    "label": (FONT_FAMILY, 16, "bold"),
    "body": (FONT_FAMILY, 15, "normal"),
    "small": (FONT_FAMILY, 14, "normal"),
    "button": (FONT_FAMILY, 15, "normal"),
    "mono": ("Consolas", 13, "normal"),
}

SPACE = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}

RADIUS = {
    "card": 6,
    "control": 5,
    "pill": 6,
}

BUTTON_HEIGHT = 38
INPUT_HEIGHT = 38
NAV_TAB_FONT = (FONT_FAMILY, 21, "bold")
NAV_TAB_HEIGHT = 72
NAV_TAB_WIDTH = 360
HEADER_HEIGHT = 92

BUTTON_STYLES = {
    "primary": {
        "fg_color": COLORS["primary"],
        "hover_color": COLORS["primary_hover"],
        "border_width": 0,
        "text_color": COLORS["text"],
    },
    "secondary": {
        "fg_color": COLORS["surface_3"],
        "hover_color": COLORS["selection_hover"],
        "border_width": 1,
        "border_color": COLORS["border"],
        "text_color": COLORS["text"],
    },
    "ghost": {
        "fg_color": "transparent",
        "hover_color": COLORS["surface_3"],
        "border_width": 1,
        "border_color": COLORS["border_soft"],
        "text_color": COLORS["text_muted"],
    },
    "danger": {
        "fg_color": COLORS["danger"],
        "hover_color": COLORS["danger_hover"],
        "border_width": 0,
        "text_color": COLORS["text"],
    },
}

ENTRY_STYLE = {
    "fg_color": COLORS["input"],
    "border_color": COLORS["border"],
    "text_color": COLORS["text"],
    "placeholder_text_color": COLORS["text_dim"],
    "corner_radius": RADIUS["control"],
    "font": FONTS["body"],
}

SEGMENTED_STYLE = {
    "fg_color": COLORS["surface_3"],
    "selected_color": COLORS["primary"],
    "selected_hover_color": COLORS["primary_hover"],
    "unselected_color": COLORS["surface_3"],
    "unselected_hover_color": COLORS["selection_hover"],
    "text_color": COLORS["text"],
    "font": FONTS["button"],
}

CHECKBOX_STYLE = {
    "fg_color": COLORS["primary"],
    "hover_color": COLORS["primary_hover"],
    "border_color": COLORS["border"],
    "text_color": COLORS["text"],
    "font": FONTS["body"],
}

COMBOBOX_STYLE = {
    "fg_color": COLORS["input"],
    "border_color": COLORS["border"],
    "text_color": COLORS["text"],
    "corner_radius": RADIUS["control"],
    "font": FONTS["body"],
    "button_color": COLORS["surface_3"],
    "button_hover_color": COLORS["selection_hover"],
}

TEXTBOX_STYLE = {
    "fg_color": COLORS["log"],
    "border_color": COLORS["border_soft"],
    "corner_radius": RADIUS["control"],
    "text_color": COLORS["text"],
    "font": FONTS["mono"],
}

SCROLLBAR_STYLE = {
    "scrollbar_button_color": COLORS["surface_3"],
    "scrollbar_button_hover_color": COLORS["selection_hover"],
}


def load_ui_font_resource() -> str | None:
    font_path = get_resource_path(FONT_RESOURCE_RELATIVE_PATH)
    if not font_path.exists():
        return f"提示：未找到界面字体文件 {FONT_RESOURCE_RELATIVE_PATH}，系统可能会使用备用字体。"
    if not sys.platform.startswith("win"):
        return None
    try:
        added = ctypes.windll.gdi32.AddFontResourceExW(str(font_path), 0x10, 0)
    except Exception as exc:  # noqa: BLE001 - font loading should never block GUI startup.
        return f"提示：界面字体加载失败：{exc}"
    if added == 0:
        return f"提示：界面字体未能注册：{FONT_RESOURCE_RELATIVE_PATH}。系统可能会使用备用字体。"
    return None
