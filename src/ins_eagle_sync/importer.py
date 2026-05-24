from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .eagle_client import EagleClient
from .metadata_parser import MediaMetadata
from .state_store import ImportedState
from .utils import build_eagle_title


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped: int


def build_annotation(item: MediaMetadata) -> str:
    lines = [
        item.caption,
        "",
        f"author: {item.author}",
        f"date: {item.date or ''}",
        f"shortcode: {item.shortcode}",
        f"source: {item.source_url}",
    ]
    return "\n".join(lines).strip()


def build_tags(item: MediaMetadata) -> list[str]:
    tags = ["instagram"]
    if item.author:
        tags.append(f"author:{item.author}")
    tags.append(f"shortcode:{item.shortcode}")
    tags.extend(item.hashtags)
    return tags


def import_metadata_items(
    items: list[MediaMetadata],
    *,
    config: AppConfig,
    eagle: EagleClient,
    state: ImportedState,
    folder_id: str,
) -> ImportResult:
    imported = 0
    skipped = 0

    for item in items:
        if state.has_imported(item.shortcode, item.media_index) or item.local_file is None:
            skipped += 1
            continue

        eagle.add_item_from_path(
            item.local_file,
            name=build_eagle_title(
                item.caption,
                item.shortcode,
                item.media_index,
                config.title_caption_chars,
            ),
            website=item.source_url,
            annotation=build_annotation(item),
            tags=build_tags(item),
            folder_id=folder_id,
        )
        state.mark_imported(item.shortcode, item.media_index)
        imported += 1

    return ImportResult(imported=imported, skipped=skipped)
