from __future__ import annotations

import argparse
import time
import tkinter as tk

import customtkinter as ctk


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe CustomTkinter resize cost.")
    parser.add_argument(
        "--mode",
        choices=("empty", "scroll", "settings", "log", "full"),
        default="full",
        help="Layout complexity to create.",
    )
    parser.add_argument("--rows", type=int, default=80, help="Number of setting rows for settings/full modes.")
    return parser.parse_args()


class ResizeProbe(ctk.CTk):
    def __init__(self, *, mode: str, rows: int) -> None:
        super().__init__()
        self.mode = mode
        self.rows = rows
        self.configure_events = 0
        self.last_report = time.monotonic()
        self.title(f"Resize Probe - {mode}")
        self.geometry("1440x900")
        self.minsize(1100, 700)
        self.configure(fg_color="#18191B")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0, minsize=430)
        self.grid_rowconfigure(0, weight=1)
        self.bind("<Configure>", self._on_configure, add="+")

        self.left = ctk.CTkFrame(self, fg_color="#1E1F22", corner_radius=6)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self.left.grid_columnconfigure(0, weight=1)
        self.left.grid_rowconfigure(0, weight=1)

        self.log = ctk.CTkFrame(self, width=430, fg_color="#222326", corner_radius=6)
        self.log.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        self.log.grid_columnconfigure(0, weight=1)
        self.log.grid_rowconfigure(1, weight=1)

        if mode in {"empty", "scroll", "settings", "full"}:
            self._build_left()
        if mode in {"log", "full"}:
            self._build_log()
        else:
            ctk.CTkLabel(self.log, text="Log disabled", text_color="#A5A8AE").grid(row=0, column=0, padx=12, pady=12)

    def _build_left(self) -> None:
        if self.mode == "empty":
            ctk.CTkLabel(self.left, text="Empty frame", text_color="#F1F2F4").grid(row=0, column=0, padx=24, pady=24)
            return

        scroll = ctk.CTkScrollableFrame(self.left, width=820, fg_color="#1E1F22", corner_radius=6)
        scroll.grid(row=0, column=0, sticky="nsw", padx=16, pady=16)
        scroll.grid_columnconfigure(0, weight=1)

        if self.mode == "scroll":
            ctk.CTkLabel(scroll, text="Scrollable frame only", text_color="#F1F2F4").grid(row=0, column=0, padx=16, pady=16)
            return

        for index in range(self.rows):
            row = ctk.CTkFrame(scroll, fg_color="#222326", border_width=1, border_color="#34363A", corner_radius=5)
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=4)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=f"Setting {index + 1}", text_color="#F1F2F4").grid(
                row=0, column=0, padx=12, pady=8, sticky="w"
            )
            ctk.CTkEntry(row, width=420, fg_color="#1A1B1E", border_color="#34363A").grid(
                row=0, column=1, padx=12, pady=8, sticky="w"
            )

    def _build_log(self) -> None:
        ctk.CTkLabel(self.log, text="Log panel", text_color="#F1F2F4").grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
        text = ctk.CTkTextbox(self.log, width=404, fg_color="#141518", border_width=1, border_color="#34363A")
        text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        for index in range(400):
            text.insert("end", f"{index:04d} resize probe log line\n")

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self.configure_events += 1
        now = time.monotonic()
        if now - self.last_report >= 1.0:
            print(f"root <Configure>/sec: {self.configure_events}")
            self.configure_events = 0
            self.last_report = now


def main() -> None:
    args = parse_args()
    ctk.set_appearance_mode("dark")
    app = ResizeProbe(mode=args.mode, rows=args.rows)
    app.mainloop()


if __name__ == "__main__":
    main()
