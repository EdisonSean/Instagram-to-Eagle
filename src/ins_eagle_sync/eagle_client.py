from __future__ import annotations

from pathlib import Path
from typing import Any

import requests


class EagleApiError(RuntimeError):
    pass


class EagleClient:
    def __init__(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")

    def check_app_available(self) -> bool:
        try:
            response = requests.get(f"{self.api_base}/api/application/info", timeout=5)
        except requests.RequestException as exc:
            raise EagleApiError(f"Eagle Local API is not available at {self.api_base}: {exc}") from exc

        _decode_eagle_response(response, action="check Eagle app availability")
        return True

    def add_item_from_path(
        self,
        import_item_or_path: Any,
        folder_id: str | None = None,
        **legacy_kwargs: Any,
    ) -> dict[str, Any]:
        payload = _build_add_item_payload(import_item_or_path, folder_id, legacy_kwargs)
        try:
            response = requests.post(f"{self.api_base}/api/item/addFromPath", json=payload, timeout=30)
        except requests.RequestException as exc:
            raise EagleApiError(f"Eagle Local API addFromPath request failed: {exc}") from exc

        return _decode_eagle_response(response, action="add item from path")


def _build_add_item_payload(
    import_item_or_path: Any,
    folder_id: str | None,
    legacy_kwargs: dict[str, Any],
) -> dict[str, Any]:
    if hasattr(import_item_or_path, "file_path"):
        if not folder_id:
            raise ValueError("folder_id is required")
        return {
            "path": str(import_item_or_path.file_path),
            "name": import_item_or_path.title,
            "website": import_item_or_path.website,
            "annotation": import_item_or_path.annotation,
            "tags": import_item_or_path.tags,
            "folderId": folder_id,
        }

    file_path = Path(import_item_or_path)
    resolved_folder_id = folder_id or legacy_kwargs.get("folder_id")
    if not resolved_folder_id:
        raise ValueError("folder_id is required")

    return {
        "path": str(file_path),
        "name": legacy_kwargs["name"],
        "website": legacy_kwargs["website"],
        "annotation": legacy_kwargs["annotation"],
        "tags": legacy_kwargs["tags"],
        "folderId": resolved_folder_id,
    }


def _decode_eagle_response(response: requests.Response, *, action: str) -> dict[str, Any]:
    body_text = response.text.strip()
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        detail = _response_detail(payload, body_text)
        raise EagleApiError(f"Eagle API failed to {action}: HTTP {response.status_code}. {detail}")

    if isinstance(payload, dict):
        status = str(payload.get("status", "")).lower()
        if status and status not in {"success", "ok"}:
            detail = _response_detail(payload, body_text)
            raise EagleApiError(f"Eagle API failed to {action}: {detail}")
        return payload

    return {"data": payload}


def _response_detail(payload: Any, body_text: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "msg"):
            if payload.get(key):
                return str(payload[key])
    return body_text or "No response body."
