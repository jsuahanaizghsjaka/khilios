"""Клиент API панели Remnawave.

Бот стоит на той же машине, что и панель, и ходит к ней по localhost —
поэтому API панели не приходится открывать наружу вообще.

────────────────────────────────────────────────────────────────────────
ВНИМАНИЕ, ПРОЧИТАТЬ ПЕРЕД ПЕРВЫМ ЗАПУСКОМ.

Пути и поля ниже — под API Remnawave, и они меняются между версиями панели.
Проверить против своей версии ОБЯЗАТЕЛЬНО, до первого живого пользователя:
панель отдаёт собственную документацию, обычно на /api/docs или /docs.

Всё, что зависит от версии, собрано здесь и помечено VERIFY. Если панель
отвечает 404 или 422 — расхождение здесь, а не в логике бота.
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx

log = logging.getLogger(__name__)

# VERIFY: пути API панели.
EP_USERS = "/api/users"
EP_USER = "/api/users/{uuid}"
EP_USER_BY_TELEGRAM = "/api/users/by-telegram-id/{telegram_id}"


class PanelError(Exception):
    """Панель не смогла выполнить запрос.

    Отличается от сетевой ошибки намеренно: сетевую имеет смысл повторить,
    эту — нет, она означает расхождение схемы или исчерпанные права токена.
    """


class PanelUnavailable(Exception):
    """Панель не отвечает. Повторить имеет смысл."""


class PanelClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise PanelUnavailable(f"{method} {path}: {exc}") from exc

        if resp.status_code >= 500:
            raise PanelUnavailable(f"{method} {path}: {resp.status_code}")
        if resp.status_code >= 400:
            raise PanelError(f"{method} {path}: {resp.status_code} {resp.text[:400]}")

        if not resp.content:
            return {}
        payload = resp.json()
        # VERIFY: Remnawave заворачивает ответ в {"response": {...}}.
        return payload.get("response", payload) if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Жива ли панель и принят ли токен.

        Вызывается на старте. Бот, поднявшийся с протухшим токеном и
        обнаруживший это на первом пользователе, — деньги уже взяты,
        а ключа нет.
        """
        try:
            await self._request("GET", EP_USERS, params={"size": 1})
            return True
        except (PanelError, PanelUnavailable) as exc:
            log.error("Панель недоступна или токен не принят: %s", exc)
            return False

    async def create_user(
        self,
        *,
        telegram_id: int,
        days: int,
        devices: int,
        tag: str,
    ) -> tuple[str, str, str]:
        """Создать пользователя. Возвращает (uuid, ссылка на подписку, expires_at).

        Лимит устройств задаётся ЗДЕСЬ, в панели, а не в боте: без HWID
        «пять устройств» превращается в ключ, разошедшийся по чату на сорок
        человек, и нода ложится для всех.
        """
        expires = _expires_at(days)

        # VERIFY: имена полей payload.
        body = {
            "username": f"tg{telegram_id}",
            "telegramId": telegram_id,
            "expireAt": expires,
            "status": "ACTIVE",
            "hwidDeviceLimit": devices,
            "trafficLimitBytes": 0,  # 0 = без лимита трафика
            "trafficLimitStrategy": "NO_RESET",
            "description": tag,
        }

        data = await self._request("POST", EP_USERS, json=body)
        return _extract(data, expires)

    async def get_by_telegram_id(self, telegram_id: int) -> dict | None:
        try:
            data = await self._request(
                "GET", EP_USER_BY_TELEGRAM.format(telegram_id=telegram_id)
            )
        except PanelError:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data or None

    async def extend(self, uuid: str, *, days: int, devices: int) -> tuple[str, str, str]:
        """Продлить подписку от большей из двух дат: сегодня или текущий конец.

        Продление за неделю до истечения не должно сжигать оплаченный остаток —
        это первый повод для спора и первый возврат.
        """
        current = await self._request("GET", EP_USER.format(uuid=uuid))
        base = _parse(current.get("expireAt"))
        now = dt.datetime.now(dt.timezone.utc)
        start = base if base and base > now else now
        expires = (start + dt.timedelta(days=days)).isoformat(timespec="seconds")

        # VERIFY: метод обновления — PATCH с uuid в теле у части версий.
        body = {
            "uuid": uuid,
            "expireAt": expires,
            "status": "ACTIVE",
            "hwidDeviceLimit": devices,
        }
        data = await self._request("PATCH", EP_USERS, json=body)
        return _extract(data, expires, fallback_uuid=uuid)

    async def disable(self, uuid: str) -> None:
        body = {"uuid": uuid, "status": "DISABLED"}
        await self._request("PATCH", EP_USERS, json=body)


# ----------------------------------------------------------------------


def _expires_at(days: int) -> str:
    return (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    ).isoformat(timespec="seconds")


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _extract(
    data: dict, expires: str, fallback_uuid: str | None = None
) -> tuple[str, str, str]:
    """Достать uuid и ссылку на подписку из ответа панели.

    Ссылку панель отдаёт сама и она указывает на SUB_HOST — то есть на домен
    подписки, а не на домен сайта. Собирать её здесь руками нельзя: домен
    подписки живёт в конфиге панели, и две копии этого знания разъедутся.
    """
    uuid = data.get("uuid") or fallback_uuid
    # VERIFY: имя поля со ссылкой.
    sub_url = data.get("subscriptionUrl") or data.get("subscription_url")

    if not uuid or not sub_url:
        raise PanelError(
            f"В ответе панели нет uuid или ссылки на подписку. Ключи: {sorted(data)}"
        )
    return uuid, sub_url, data.get("expireAt") or expires
