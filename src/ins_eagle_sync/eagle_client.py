from __future__ import annotations

from pathlib import Path
from typing import Any

import requests


class EagleClient:
    def __init__(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")

    def add_item_from_path(
        self,
        file_path: Path,
        *,
        name: str,
        website: str,
        annotation: str,
        tags: list[str],
        folder_id: str,
    ) -> dict[str, Any]:
        payload = {
            "path": str(file_path),
            "name": name,
            "website": website,
            "annotation": annotation,
            "tags": tags,
            "folderId": folder_id,
        }
        response = requests.post(f"{self.api_base}/api/item/addFromPath", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
