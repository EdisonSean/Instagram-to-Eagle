from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests


class EagleApiError(RuntimeError):
    pass


ITEM_ALIVE = "alive"
ITEM_MISSING = "missing"
ITEM_UNKNOWN = "unknown"
ITEM_ALIVE_IN_FOLDER = "alive_in_folder"
ITEM_ALIVE_BUT_NOT_IN_FOLDER = "alive_but_not_in_folder"


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

    def list_folders(self) -> list[dict[str, str | None]]:
        try:
            response = requests.get(f"{self.api_base}/api/folder/list", timeout=10)
        except requests.RequestException as exc:
            raise EagleApiError(f"Eagle Local API folder list request failed: {exc}") from exc

        payload = _decode_eagle_response(response, action="list folders")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        return _flatten_folder_tree(data)

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, str | None]:
        payload = {"folderName": name}
        if parent_id:
            payload["parent"] = parent_id

        try:
            response = requests.post(f"{self.api_base}/api/folder/create", json=payload, timeout=10)
        except requests.RequestException as exc:
            raise EagleApiError(f"Eagle Local API folder create request failed for {name}: {exc}") from exc

        decoded = _decode_eagle_response(response, action=f"create folder {name}")
        data = decoded.get("data") if isinstance(decoded, dict) else None
        if not isinstance(data, dict) or not data.get("id"):
            raise EagleApiError(f"Eagle API did not return a folder id when creating {name}")

        return {
            "id": str(data["id"]),
            "name": str(data.get("name") or name),
            "parent_id": parent_id,
            "path": "",
        }

    def ensure_folder_path(self, folder_path: str) -> str:
        segments = _split_folder_path(folder_path)
        folders = self.list_folders()
        current_parent_id: str | None = None
        current_path = ""

        for segment in segments:
            current_path = f"{current_path}/{segment}" if current_path else segment
            existing = _find_folder_child(folders, name=segment, parent_id=current_parent_id)
            if existing is None:
                created = self.create_folder(segment, current_parent_id)
                created["path"] = current_path
                folders.append(created)
                existing = created
            current_parent_id = str(existing["id"])

        if not current_parent_id:
            raise EagleApiError(f"Invalid Eagle folder path: {folder_path}")
        return current_parent_id

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

    def item_exists_in_folder(self, item_id: str, folder_id: str) -> str:
        data = self.get_item_info(item_id)
        if not data or data.get("isDeleted") is True:
            return ITEM_MISSING

        if _has_folder_info(data):
            return ITEM_ALIVE_IN_FOLDER if _item_is_in_folder(data, folder_id) else ITEM_ALIVE_BUT_NOT_IN_FOLDER

        if self._item_list_confirms_item_in_folder(item_id, folder_id, data):
            return ITEM_ALIVE_IN_FOLDER
        return ITEM_ALIVE_BUT_NOT_IN_FOLDER

    def _item_list_confirms_item_in_folder(
        self,
        item_id: str,
        folder_id: str,
        item_info: dict[str, Any],
    ) -> bool:
        for item in self.list_items(folder_id=folder_id):
            if _listed_item_confirms_folder_membership(item, item_id, item_info):
                return True
        return False

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
        matches: list[str] = []
        while checked < max_items:
            page = self.list_items(limit=limit, offset=offset, folder_id=folder_id)
            if not page:
                break

            for item in page:
                checked += 1
                if _item_matches_import_item(item, import_item, folder_id):
                    matches.append(str(item.get("id") or ""))
                    if len(matches) > 1:
                        raise EagleApiError("multiple Eagle items matched, manual cleanup required")

            if len(page) < limit:
                break
            offset += limit

        return matches[0] if matches else ""


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


def _flatten_folder_tree(
    folders: list[Any],
    *,
    parent_id: str | None = None,
    parent_path: str = "",
) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []
    for folder in folders:
        if not isinstance(folder, dict) or not folder.get("id") or not folder.get("name"):
            continue

        folder_id = str(folder["id"])
        name = str(folder["name"])
        resolved_parent_id = _folder_parent_id(folder) or parent_id
        path = f"{parent_path}/{name}" if parent_path else name
        entries.append(
            {
                "id": folder_id,
                "name": name,
                "parent_id": resolved_parent_id,
                "path": path,
            }
        )

        children = folder.get("children")
        if not isinstance(children, list) or not children:
            children = folder.get("folders")
        if isinstance(children, list):
            entries.extend(_flatten_folder_tree(children, parent_id=folder_id, parent_path=path))

    return entries


def _folder_parent_id(folder: dict[str, Any]) -> str | None:
    for key in ("parent", "parentId", "parent_id"):
        value = folder.get(key)
        if isinstance(value, dict):
            for nested_key in ("id", "folderId", "folder_id"):
                nested_value = value.get(nested_key)
                if nested_value:
                    return str(nested_value)
        elif value:
            return str(value)
    return None


def _split_folder_path(folder_path: str) -> list[str]:
    parts = [part.strip() for part in folder_path.replace("\\", "/").split("/")]
    segments = [part for part in parts if part]
    if not segments:
        raise EagleApiError("folder path must not be empty")
    return segments


def _find_folder_child(
    folders: list[dict[str, str | None]],
    *,
    name: str,
    parent_id: str | None,
) -> dict[str, str | None] | None:
    matches = [
        folder
        for folder in folders
        if folder.get("name") == name and _same_optional_id(folder.get("parent_id"), parent_id)
    ]
    if len(matches) > 1:
        parent_label = parent_id or "<root>"
        raise EagleApiError(f"Multiple Eagle folders named {name!r} exist under parent {parent_label}")
    return matches[0] if matches else None


def _same_optional_id(left: str | None, right: str | None) -> bool:
    return (left or "") == (right or "")


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
            "\u4e0d\u5b58\u5728",
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

    if folder_id and not _item_is_in_folder(item, folder_id):
        return False

    item_url = str(item.get("url") or item.get("website") or "")
    if item_url != str(import_item.website):
        return False

    annotation = _normalize_multiline_text(str(item.get("annotation") or ""))
    if not _annotation_has_shortcode(annotation, str(import_item.shortcode)):
        return False

    return _annotation_has_media_index(annotation, int(import_item.media_index))


def _item_is_in_folder(item: dict[str, Any], folder_id: str) -> bool:
    return folder_id in _extract_folder_ids(item)


def _has_folder_info(item: dict[str, Any]) -> bool:
    return any(key in item for key in ("folderId", "folder_id", "folderIds", "folder_ids", "parent", "folders"))


def _extract_folder_ids(item: dict[str, Any]) -> set[str]:
    folder_values: set[str] = set()
    for key in ("folderId", "folder_id"):
        value = item.get(key)
        if value:
            folder_values.add(str(value))

    for key in ("folderIds", "folder_ids"):
        values = item.get(key)
        if isinstance(values, list):
            folder_values.update(str(value) for value in values if value)

    parent = item.get("parent")
    if isinstance(parent, dict):
        for key in ("id", "folderId", "folder_id"):
            value = parent.get(key)
            if value:
                folder_values.add(str(value))
    elif parent:
        folder_values.add(str(parent))

    folders = item.get("folders")
    if isinstance(folders, list):
        for folder in folders:
            if isinstance(folder, dict):
                for key in ("id", "folderId", "folder_id"):
                    value = folder.get(key)
                    if value:
                        folder_values.add(str(value))
            elif folder:
                folder_values.add(str(folder))

    return folder_values


def _listed_item_confirms_folder_membership(
    item: dict[str, Any],
    item_id: str,
    item_info: dict[str, Any],
) -> bool:
    listed_id = str(item.get("id") or "")
    if listed_id:
        return listed_id == item_id

    info_url = str(item_info.get("url") or item_info.get("website") or "")
    item_url = str(item.get("url") or item.get("website") or "")
    if not info_url or item_url != info_url:
        return False

    info_annotation = _normalize_multiline_text(str(item_info.get("annotation") or ""))
    item_annotation = _normalize_multiline_text(str(item.get("annotation") or ""))
    return bool(info_annotation and item_annotation == info_annotation)


def _annotation_has_shortcode(annotation: str, shortcode: str) -> bool:
    return _annotation_has_labeled_value(annotation, ["Shortcode"], shortcode)


def _annotation_has_media_index(annotation: str, media_index: int) -> bool:
    index = f"{media_index:02d}"
    return _annotation_has_labeled_value(
        annotation,
        ["\u5e8f\u53f7", "Index", "Media Index", "搴忓彿"],
        index,
    )


def _annotation_has_labeled_value(annotation: str, labels: list[str], value: str) -> bool:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:\uff1a]\s*{re.escape(value)}(?=$|[^\w-])"
        if re.search(pattern, annotation, flags=re.IGNORECASE):
            return True
    return False


def _normalize_multiline_text(value: str) -> str:
    return "\n".join(value.replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()


def _response_detail(payload: Any, body_text: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "msg", "data"):
            if payload.get(key):
                return str(payload[key])
    return body_text or "No response body."
