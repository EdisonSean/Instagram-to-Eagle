from __future__ import annotations

import os
from typing import Any, Mapping

PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def normalize_proxy_url(proxy: str | None, *, scheme: str = "http") -> str:
    text = str(proxy or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "://" in lowered:
        return text
    if scheme.lower().startswith("socks"):
        return f"socks5://{text}"
    return f"http://{text}"


def parse_windows_proxy_server(value: str | None) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}

    if "=" not in text:
        proxy = normalize_proxy_url(text)
        return {"http": proxy, "https": proxy}

    parsed: dict[str, str] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, raw_proxy = part.split("=", 1)
        key = key.strip().lower()
        raw_proxy = raw_proxy.strip()
        if not raw_proxy:
            continue
        if key in {"http", "https"}:
            parsed[key] = normalize_proxy_url(raw_proxy)
        elif key in {"socks", "socks5"}:
            parsed["http"] = normalize_proxy_url(raw_proxy, scheme="socks5")
            parsed["https"] = normalize_proxy_url(raw_proxy, scheme="socks5")

    if "http" in parsed and "https" not in parsed:
        parsed["https"] = parsed["http"]
    if "https" in parsed and "http" not in parsed:
        parsed["http"] = parsed["https"]
    return parsed


def detect_system_proxy(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    env = environ if environ is not None else os.environ
    env_proxy = _proxy_from_environment(env)
    if env_proxy:
        return env_proxy
    return _proxy_from_windows_registry()


def build_proxy_env(
    proxy_config: Any,
    *,
    base_env: Mapping[str, str] | None = None,
    detector: Any = detect_system_proxy,
) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    _clear_proxy_env(env)

    mode = str(getattr(proxy_config, "mode", "") or "").strip().lower()
    if not mode:
        mode = "manual" if getattr(proxy_config, "enabled", False) else "none"

    proxies: dict[str, str] = {}
    if mode == "manual":
        http_proxy = normalize_proxy_url(getattr(proxy_config, "http_proxy", "") or "")
        https_proxy = normalize_proxy_url(getattr(proxy_config, "https_proxy", "") or "")
        if http_proxy and not https_proxy:
            https_proxy = http_proxy
        elif https_proxy and not http_proxy:
            http_proxy = https_proxy
        proxies = {"http": http_proxy, "https": https_proxy}
    elif mode == "auto":
        detected = detector() or {}
        if isinstance(detected, str):
            proxies = parse_windows_proxy_server(detected)
        elif isinstance(detected, Mapping):
            proxies = {
                "http": normalize_proxy_url(str(detected.get("http") or detected.get("HTTP_PROXY") or "")),
                "https": normalize_proxy_url(str(detected.get("https") or detected.get("HTTPS_PROXY") or "")),
            }
            if proxies["http"] and not proxies["https"]:
                proxies["https"] = proxies["http"]
            elif proxies["https"] and not proxies["http"]:
                proxies["http"] = proxies["https"]

    http_proxy = proxies.get("http") or ""
    https_proxy = proxies.get("https") or ""
    if http_proxy:
        env["HTTP_PROXY"] = http_proxy
    if https_proxy:
        env["HTTPS_PROXY"] = https_proxy
    return env


def proxy_mode_label(mode: str) -> str:
    normalized = str(mode or "auto").lower()
    if normalized == "manual":
        return "手动设置"
    if normalized == "none":
        return "不使用代理"
    return "自动检测"


def _proxy_from_environment(env: Mapping[str, str]) -> dict[str, str]:
    http_proxy = _first_env_value(env, ("HTTP_PROXY", "http_proxy"))
    https_proxy = _first_env_value(env, ("HTTPS_PROXY", "https_proxy"))
    all_proxy = _first_env_value(env, ("ALL_PROXY", "all_proxy"))
    if all_proxy:
        http_proxy = http_proxy or all_proxy
        https_proxy = https_proxy or all_proxy
    if not http_proxy and not https_proxy:
        return {}
    http_proxy = normalize_proxy_url(http_proxy or https_proxy)
    https_proxy = normalize_proxy_url(https_proxy or http_proxy)
    return {"http": http_proxy, "https": https_proxy}


def _proxy_from_windows_registry() -> dict[str, str]:
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            try:
                proxy_enable = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            except OSError:
                proxy_enable = 0
            if not proxy_enable:
                return {}
            try:
                proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0])
            except OSError:
                return {}
    except Exception:
        return {}
    return parse_windows_proxy_server(proxy_server)


def _first_env_value(env: Mapping[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = env.get(key)
        if value:
            return str(value).strip()
    return ""


def _clear_proxy_env(env: dict[str, str]) -> None:
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)
