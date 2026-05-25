from types import SimpleNamespace

from ins_eagle_sync.proxy_utils import (
    build_proxy_env,
    detect_system_proxy,
    normalize_proxy_url,
    parse_windows_proxy_server,
)


def test_detect_system_proxy_reads_environment() -> None:
    detected = detect_system_proxy({"HTTP_PROXY": "127.0.0.1:10809"})

    assert detected == {
        "http": "http://127.0.0.1:10809",
        "https": "http://127.0.0.1:10809",
    }


def test_parse_windows_proxy_server_plain_host_port() -> None:
    assert parse_windows_proxy_server("127.0.0.1:10809") == {
        "http": "http://127.0.0.1:10809",
        "https": "http://127.0.0.1:10809",
    }


def test_parse_windows_proxy_server_protocol_map() -> None:
    assert parse_windows_proxy_server("http=127.0.0.1:10809;https=127.0.0.1:10810") == {
        "http": "http://127.0.0.1:10809",
        "https": "http://127.0.0.1:10810",
    }


def test_parse_windows_proxy_server_socks() -> None:
    assert parse_windows_proxy_server("socks=127.0.0.1:10808") == {
        "http": "socks5://127.0.0.1:10808",
        "https": "socks5://127.0.0.1:10808",
    }


def test_normalize_proxy_url_adds_http_scheme() -> None:
    assert normalize_proxy_url("127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert normalize_proxy_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_build_proxy_env_auto_uses_detected_proxy() -> None:
    proxy = SimpleNamespace(mode="auto", enabled=True, http_proxy="", https_proxy="")

    env = build_proxy_env(
        proxy,
        base_env={},
        detector=lambda: {"http": "127.0.0.1:10809", "https": "127.0.0.1:10809"},
    )

    assert env["HTTP_PROXY"] == "http://127.0.0.1:10809"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:10809"


def test_build_proxy_env_auto_without_proxy_clears_proxy_vars() -> None:
    proxy = SimpleNamespace(mode="auto", enabled=True, http_proxy="", https_proxy="")

    env = build_proxy_env(
        proxy,
        base_env={"HTTP_PROXY": "http://old", "HTTPS_PROXY": "http://old", "ALL_PROXY": "http://old"},
        detector=lambda: {},
    )

    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert "ALL_PROXY" not in env


def test_build_proxy_env_manual_uses_configured_proxy() -> None:
    proxy = SimpleNamespace(mode="manual", enabled=True, http_proxy="127.0.0.1:10809", https_proxy="127.0.0.1:10810")

    env = build_proxy_env(proxy, base_env={})

    assert env["HTTP_PROXY"] == "http://127.0.0.1:10809"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:10810"


def test_build_proxy_env_manual_copies_http_to_https() -> None:
    proxy = SimpleNamespace(mode="manual", enabled=True, http_proxy="127.0.0.1:10809", https_proxy="")

    env = build_proxy_env(proxy, base_env={})

    assert env["HTTP_PROXY"] == "http://127.0.0.1:10809"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:10809"


def test_build_proxy_env_none_removes_proxy_vars() -> None:
    proxy = SimpleNamespace(mode="none", enabled=False, http_proxy="", https_proxy="")

    env = build_proxy_env(
        proxy,
        base_env={"HTTP_PROXY": "http://old", "HTTPS_PROXY": "http://old", "ALL_PROXY": "http://old"},
    )

    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert "ALL_PROXY" not in env
