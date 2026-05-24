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

    def get_item_info(self, item_id: str) -> dict[str, Any] | None:
        if not item_id:
            return None

        try:
            response = requests.get(f"{self.api_base}/api/item/info", params={"id": item_id}, timeout=10)
        except requests.RequestException as exc:
            raise EagleApiError(f"Eagle Local API item info request failed for {item_id}: {exc}") from exc

        payload = _decode_eagle_response(
            response,
            action=f"get item info for {item_id}",
            allow_not_found=True,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    def item_exists(self, item_id: str) -> bool | None:
        data = self.get_item_info(item_id)
        if not data:
            return False
        return data.get("isDeleted") is not True

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

        decoded = _decode_eagle_response(response, action="add item from path")
        eagle_item_id = extract_eagle_item_id(decoded)
        if not eagle_item_id and hasattr(import_item_or_path, "file_path"):
            try:
                eagle_item_id = self.find_matching_item_id(import_item_or_path, folder_id)
            except EagleApiError:
                eagle_item_id = ""
        if eagle_item_id:
            decoded["eagle_item_id"] = eagle_item_id
        return decoded

    def list_items(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        order_by: str = "-CREATEDATE",
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "orderBy": order_by,
        }
        if folder_id:
            params["folders"] = folder_id

        try:
            response = requests.get(f"{self.api_base}/api/item/list", params=params, timeout=10)
        except requests.RequestException as exc:
            raise EagleApiError(f"Eagle Local API item list request failed: {exc}") from exc

        payload = _decode_eagle_response(response, action="list items")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def find_matching_item_id(
        self,
        import_item: Any,
        folder_id: str | None = None,
        *,
        limit: int = 200,
        max_items: int = 2000,
    ) -> str:
        offset = 0
        checked = 0
        while checked < max_items:
            page = self.list_items(limit=limit, offset=offset, folder_id=folder_id)
            if not page:
                return ""

            for item in page:
                checked += 1
                if _item_matches_import_item(item, import_item, folder_id):
                    return str(item.get("id") or "")

            if len(page) < limit:
                return ""
            offset += limit

        return ""


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


def extract_eagle_item_id(response: dict[str, Any]) -> str:
    return _extract_id_from_value(response)


def _decode_eagle_response(
    response: requests.Response,
    *,
    action: str,
    allow_not_found: bool = False,
) -> dict[str, Any]:
    body_text = response.text.strip()
    try:
        payload = response.json()
    except ValueError as exc:
        if allow_not_found and response.status_code == 404:
            return {"data": None}
        raise EagleApiError(f"Eagle API failed to {action}: invalid JSON response. {body_text}") from exc

    if allow_not_found and _is_not_found_response(response.status_code, payload):
        return {"data": None}

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


def _extract_id_from_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("eagle_item_id", "id", "itemId", "item_id"):
            if value.get(key):
                return str(value[key])

        for key in ("data", "item", "items", "result"):
            item_id = _extract_id_from_value(value.get(key))
            if item_id:
                return item_id

    if isinstance(value, list):
        for item in value:
            item_id = _extract_id_from_value(item)
            if item_id:
                return item_id

    return ""


def _is_not_found_response(status_code: int, payload: Any) -> bool:
    if status_code == 404:
        return True

    if isinstance(payload, dict) and _data_says_file_does_not_exist(payload.get("data")):
        return True

    if status_code >= 400:
        return False

    if not isinstance(payload, dict):
        return False

    status = str(payload.get("status", "")).lower()
    if status in {"success", "ok"}:
        return False

    detail = _response_detail(payload, "").lower()
    return any(
        marker in detail
        for marker in (
            "not found",
            "does not exist",
            "not exist",
            "missing",
            "不存在",
        )
    )


def _data_says_file_does_not_exist(value: Any) -> bool:
    if isinstance(value, str):
        return "file does not exist" in value.lower()

    if isinstance(value, dict):
        return any(_data_says_file_does_not_exist(item) for item in value.values())

    if isinstance(value, list):
        return any(_data_says_file_does_not_exist(item) for item in value)

    return False


def _item_matches_import_item(item: dict[str, Any], import_item: Any, folder_id: str | None) -> bool:
    if not item.get("id"):
        return False
    if item.get("isDeleted") is True:
        return False

    if folder_id:
        folders = item.get("folders")
        if not isinstance(folders, list) or folder_id not in {str(folder) for folder in folders}:
            return False

    item_url = str(item.get("url") or item.get("website") or "")
    if item_url != str(import_item.website):
        return False

    if str(item.get("name") or "") != str(import_item.title):
        return False

    item_annotation = _normalize_multiline_text(str(item.get("annotation") or ""))
    import_annotation = _normalize_multiline_text(str(import_item.annotation))
    return item_annotation == import_annotation


def _normalize_multiline_text(value: str) -> str:
    return "\n".join(value.replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()


def _response_detail(payload: Any, body_text: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "msg", "data"):
            if payload.get(key):
                return str(payload[key])
    return body_text or "No response body."
