from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def import_key(shortcode: str, media_index: int) -> str:
    return f"{shortcode}:{media_index}"


@dataclass
class ForgetImportResult:
    matched_count: int
    removed_count: int
    removed_keys: list[str]
    backup_path: Path | None = None


@dataclass
class ImportedState:
    path: Path
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "ImportedState":
        state_path = Path(path)
        if not state_path.exists():
            return cls(path=state_path)

        data = json.loads(state_path.read_text(encoding="utf-8-sig"))
        return cls(path=state_path, records=_parse_state_data(data))

    @property
    def imported(self) -> set[str]:
        return set(self.records)

    def has_unique_key(self, unique_key: str) -> bool:
        return unique_key in self.records

    def mark_item_imported(
        self,
        import_item: Any,
        *,
        eagle_item_id: str | None = None,
        imported_at: str | None = None,
    ) -> None:
        self.records[import_item.unique_key] = {
            "file_path": str(import_item.file_path),
            "website": import_item.website,
            "title": import_item.title,
            "eagle_item_id": eagle_item_id or "",
            "imported_at": imported_at or _utc_now(),
        }

    def has_imported(self, shortcode: str, media_index: int) -> bool:
        return import_key(shortcode, media_index) in self.records

    def mark_imported(self, shortcode: str, media_index: int) -> None:
        key = import_key(shortcode, media_index)
        self.records[key] = {
            "file_path": "",
            "website": "",
            "title": "",
            "eagle_item_id": "",
            "imported_at": _utc_now(),
        }

    def find_keys(
        self,
        *,
        unique_key: str | None = None,
        shortcode: str | None = None,
        username: str | None = None,
    ) -> list[str]:
        if unique_key:
            return [unique_key] if unique_key in self.records else []

        if not shortcode:
            return []

        matches: list[str] = []
        for key in self.records:
            parsed = parse_instagram_unique_key(key)
            if parsed is None:
                continue
            key_username, key_shortcode, _media_index = parsed
            if key_shortcode != shortcode:
                continue
            if username and key_username != username:
                continue
            matches.append(key)
        return sorted(matches)

    def forget(
        self,
        *,
        unique_key: str | None = None,
        shortcode: str | None = None,
        username: str | None = None,
        dry_run: bool = False,
    ) -> ForgetImportResult:
        matched_keys = self.find_keys(unique_key=unique_key, shortcode=shortcode, username=username)
        if dry_run or not matched_keys:
            return ForgetImportResult(
                matched_count=len(matched_keys),
                removed_count=0,
                removed_keys=matched_keys,
            )

        backup_path = self.backup()
        for key in matched_keys:
            self.records.pop(key, None)
        self.save()
        return ForgetImportResult(
            matched_count=len(matched_keys),
            removed_count=len(matched_keys),
            removed_keys=matched_keys,
            backup_path=backup_path,
        )

    def backup(self) -> Path | None:
        if not self.path.exists():
            return None
        backup_path = self.path.with_name(f"{self.path.name}.bak")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, backup_path)
        return backup_path

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: self.records[key] for key in sorted(self.records)}
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def parse_instagram_unique_key(unique_key: str) -> tuple[str, str, str] | None:
    parts = unique_key.split(":")
    if len(parts) != 4 or parts[0] != "instagram":
        return None
    return parts[1], parts[2], parts[3]


def _parse_state_data(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        return {}

    legacy_imported = data.get("imported")
    if isinstance(legacy_imported, list):
        return {
            str(key): {
                "file_path": "",
                "website": "",
                "title": "",
                "eagle_item_id": "",
                "imported_at": "",
            }
            for key in legacy_imported
        }

    records: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            records[str(key)] = value
        else:
            records[str(key)] = {
                "file_path": "",
                "website": "",
                "title": "",
                "eagle_item_id": str(value),
                "imported_at": "",
            }
    return records


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
