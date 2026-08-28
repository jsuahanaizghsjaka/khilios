#!/usr/bin/env python3
"""End-to-end smoke test for every VLESS link in one Remnawave subscription.

The script intentionally never prints the subscription URL, user UUIDs, public
keys or short IDs.  It is designed to run on an administration host that has an
Xray binary and curl installed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request


def load_subscription(sqlite_path: str, telegram_id: int) -> str:
    with sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT sub_url FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("subscription URL is missing for this Telegram user")
    request = urllib.request.Request(row[0], headers={"User-Agent": "khilios-e2e/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8").strip()


def decode_links(payload: str) -> list[str]:
    if payload.startswith("vless://"):
        decoded = payload
    else:
        padded = payload + "=" * ((4 - len(payload) % 4) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
    links = [line.strip() for line in decoded.splitlines() if line.startswith("vless://")]
    if not links:
        raise RuntimeError("subscription contains no VLESS links")
    return links


def first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def client_config(link: str, socks_port: int) -> tuple[str, dict]:
    parsed = urllib.parse.urlsplit(link)
    query = urllib.parse.parse_qs(parsed.query)
    transport = first(query, "type", "raw")
    if transport == "tcp":
        transport = "raw"

    user: dict[str, str] = {
        "id": urllib.parse.unquote(parsed.username or ""),
        "encryption": first(query, "encryption", "none"),
    }
    flow = first(query, "flow")
    if flow:
        user["flow"] = flow

    stream: dict = {
        "network": transport,
        "security": first(query, "security", "reality"),
        "realitySettings": {
            "serverName": first(query, "sni"),
            "fingerprint": first(query, "fp", "chrome"),
            "publicKey": first(query, "pbk"),
            "shortId": first(query, "sid"),
            "spiderX": first(query, "spx", "/"),
        },
    }
    if transport == "xhttp":
        xhttp: dict[str, str] = {
            "path": first(query, "path", "/"),
            "mode": first(query, "mode", "auto"),
        }
        host = first(query, "host")
        if host:
            xhttp["host"] = host
        stream["xhttpSettings"] = xhttp

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": parsed.hostname,
                            "port": parsed.port,
                            "users": [user],
                        }
                    ]
                },
                "streamSettings": stream,
            }
        ],
    }
    remark = urllib.parse.unquote(parsed.fragment) or f"server-{socks_port}"
    return remark, config


def wait_for_port(port: int, process: subprocess.Popen, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Xray exited before opening the local SOCKS port")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Xray did not open the local SOCKS port")


def curl_via(port: int, url: str, *, body: bool = False) -> str:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "8",
        "--max-time",
        "20",
        "--socks5-hostname",
        f"127.0.0.1:{port}",
    ]
    if body:
        command.extend(["--fail", url])
    else:
        command.extend(["--output", os.devnull, "--write-out", "%{http_code}", url])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--telegram-id", required=True, type=int)
    parser.add_argument("--xray", required=True)
    args = parser.parse_args()

    links = decode_links(load_subscription(args.sqlite, args.telegram_id))
    failures = 0
    with tempfile.TemporaryDirectory(prefix="khilios-e2e-") as directory:
        for index, link in enumerate(links):
            port = 23000 + index
            remark, config = client_config(link, port)
            config_path = os.path.join(directory, f"client-{index}.json")
            log_path = os.path.join(directory, f"client-{index}.log")
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, ensure_ascii=False)
            os.chmod(config_path, 0o600)

            with open(log_path, "w", encoding="utf-8") as log_file:
                process = subprocess.Popen(
                    [args.xray, "run", "-c", config_path],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
                try:
                    wait_for_port(port, process)
                    egress = curl_via(port, "https://api.ipify.org", body=True)
                    telegram_code = curl_via(port, "https://telegram.org")
                    api_code = curl_via(port, "https://api.telegram.org/botinvalid/getMe")
                    if not egress or telegram_code == "000" or api_code == "000":
                        raise RuntimeError("one or more HTTPS probes did not complete")
                    print(
                        f"PASS {index + 1}/{len(links)} {remark}: "
                        f"internet=yes telegram={telegram_code} telegram-api={api_code}"
                    )
                except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
                    failures += 1
                    print(f"FAIL {index + 1}/{len(links)} {remark}: {type(error).__name__}")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)

    print(f"SUMMARY total={len(links)} passed={len(links) - failures} failed={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
