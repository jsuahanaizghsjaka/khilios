"""Контракт с Remnawave 2.8: маршруты, id пользователя и payload."""

from __future__ import annotations

import json

import httpx
import pytest

from app.panel import PanelClient, PanelError

SQUADS = ("11111111-1111-4111-8111-111111111111",)


def _response(**over):
    base = {
        "id": 42,
        "subscriptionUrl": "https://sub.example/abc",
        "expireAt": "2030-01-01T00:00:00.000Z",
    }
    base.update(over)
    return {"response": base}


@pytest.mark.asyncio
async def test_create_user_uses_current_contract():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=_response())

    panel = PanelClient("https://panel.example", "token", internal_squads=SQUADS)
    await panel._client.aclose()
    panel._client = httpx.AsyncClient(
        base_url="https://panel.example",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer token"},
    )
    try:
        user_id, sub_url, expires = await panel.create_user(
            telegram_id=123, days=7, devices=1, tag="trial"
        )
    finally:
        await panel.close()

    assert (user_id, sub_url) == ("42", "https://sub.example/abc")
    assert expires == "2030-01-01T00:00:00.000Z"
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/users"
    body = json.loads(requests[0].content)
    assert body["username"] == "tg123"
    assert body["telegramId"] == 123
    assert body["hwidDeviceLimit"] == 1
    assert body["activeInternalSquads"] == list(SQUADS)


@pytest.mark.asyncio
async def test_extend_uses_action_then_enables_and_updates_limit():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/actions/extend"):
            return httpx.Response(200, json=_response())
        return httpx.Response(200, json=_response())

    panel = PanelClient("https://panel.example", "token", internal_squads=SQUADS)
    await panel._client.aclose()
    panel._client = httpx.AsyncClient(
        base_url="https://panel.example", transport=httpx.MockTransport(handler)
    )
    try:
        result = await panel.extend("42", days=30, devices=5)
    finally:
        await panel.close()

    assert result[0] == "42"
    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", "/api/users/42/actions/extend"),
        ("PATCH", "/api/users"),
    ]
    assert json.loads(requests[0].content) == {"days": 30}
    assert json.loads(requests[1].content) == {
        "id": 42,
        "status": "ACTIVE",
        "hwidDeviceLimit": 5,
    }


@pytest.mark.asyncio
async def test_disable_uses_current_action_route():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_response(status="DISABLED"))

    panel = PanelClient("https://panel.example", "token", internal_squads=SQUADS)
    await panel._client.aclose()
    panel._client = httpx.AsyncClient(
        base_url="https://panel.example", transport=httpx.MockTransport(handler)
    )
    try:
        await panel.disable("42")
    finally:
        await panel.close()

    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", "/api/users/42/actions/disable")
    ]


@pytest.mark.asyncio
async def test_old_uuid_fails_loudly_instead_of_calling_wrong_route():
    panel = PanelClient("https://panel.example", "token", internal_squads=SQUADS)
    try:
        with pytest.raises(PanelError, match="числовой id"):
            await panel.disable("c5b5f650-4194-4c55-b3b6-6d3a20c21244")
    finally:
        await panel.close()
