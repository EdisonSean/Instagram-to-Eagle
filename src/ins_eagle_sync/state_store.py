from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def import_key(shortcode: str, media_index: int) -> str:
    return f"{shortcode}:{media_index}"


@dataclass
class ImportedState:
    path: Path
    imported: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: str | Path) -> "ImportedState":
        state_path = Path(path)
        if not state_path.exists():
            return cls(path=state_path)

        data = json.loads(state_path.read_text(encoding="utf-8"))
        imported = data.get("imported", [])
        return cls(path=state_path, imported=set(map(str, imported)))

    def has_imported(self, shortcode: str, media_index: int) -> bool:
        return import_key(shortcode, media_index) in self.imported

    def mark_imported(self, shortcode: str, media_index: int) -> None:
        self.imported.add(import_key(shortcode, media_index))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"imported": sorted(self.imported)}
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
