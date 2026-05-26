from __future__ import annotations

from pathlib import Path


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - developer utility.
        raise SystemExit("Pillow is required. Run: py -m pip install pillow") from exc

    repo_root = Path(__file__).resolve().parents[1]
    assets_dir = repo_root / "assets"
    source = assets_dir / "app_icon.png"
    if not source.exists():
        source = assets_dir / "icon.png"
    if not source.exists():
        raise SystemExit("No source PNG found. Expected assets/app_icon.png or assets/icon.png")

    output = assets_dir / "app_icon.ico"
    image = Image.open(source).convert("RGBA")
    image.save(output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
