from __future__ import annotations

from app.config import load


def test_load_accepts_docker_run_env_file_quotes(monkeypatch) -> None:
    values = {
        "BOT_TOKEN": '"123456:test"',
        "ADMIN_TELEGRAM_ID": '"42"',
        "PANEL_API_URL": '"http://127.0.0.1:3002"',
        "PANEL_API_TOKEN": '"panel-token"',
        "PANEL_INTERNAL_SQUADS": '"96e666e6-3e9d-4970-82ad-7524fec6ef9c"',
        "CHANNEL_USERNAME": '"@khilios_vpn"',
        "STARS_ENABLED": '"false"',
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = load()

    assert config.bot_token == "123456:test"
    assert config.admin_id == 42
    assert config.panel_api_url == "http://127.0.0.1:3002"
    assert config.panel_api_token == "panel-token"
    assert config.panel_internal_squads == (
        "96e666e6-3e9d-4970-82ad-7524fec6ef9c",
    )
    assert config.channel == "@khilios_vpn"
    assert config.stars_enabled is False
