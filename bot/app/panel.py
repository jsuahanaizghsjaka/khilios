"""Клиент API панели Remnawave.

Бот стоит на той же машине, что и панель, и ходит к ней по localhost —
поэтому API панели не приходится открывать наружу вообще.

────────────────────────────────────────────────────────────────────────
Контракт клиента проверен на Remnawave 3.2.3. Пользователь адресуется числовым
``id``: UUID из старых примеров API не подходит для GET и action-маршрутов.
Перед следующим обновлением панели контракт снова проверяется тестами этого
модуля и сверяется с OpenAPI установленной панели.
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx

log = logging.getLogger(__name__)

EP_USERS = "/api/users"
EP_USER = "/api/users/{user_id}"
EP_USER_BY_USERNAME = "/api/users/by-username/{username}"
EP_EXTEND = "/api/users/{user_id}/actions/extend"
EP_DISABLE = "/api/users/{user_id}/actions/disable"


class PanelError(Exception):
    """Панель не смогла выполнить запрос.

    Отличается от сетевой ошибки намеренно: сетевую имеет смысл повторить,
    эту — нет, она означает расхождение схемы или исчерпанные права токена.
    """


class PanelUnavailable(Exception):
    """Панель не отвечает. Повторить имеет смысл."""


class PanelClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        internal_squads: tuple[str, ...],
        timeout: float = 10.0,
    ) -> None:
        if not internal_squads:
            raise ValueError("Нужна хотя бы одна внутренняя группа Remnawave")
        self._internal_squads = internal_squads
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
        # Все защищённые методы Remnawave 2.x заворачивают данные в response.
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

        body = {
            "username": f"tg{telegram_id}",
            "telegramId": telegram_id,
            "expireAt": expires,
            "status": "ACTIVE",
            "hwidDeviceLimit": devices,
            "trafficLimitBytes": 0,  # 0 = без лимита трафика
            "trafficLimitStrategy": "NO_RESET",
            "description": tag,
            # Без группы пользователь существует, но его подписка не содержит
            # ни одного узла — внешне это выглядит как нерабочий ключ.
            "activeInternalSquads": list(self._internal_squads),
        }

        data = await self._request("POST", EP_USERS, json=body)
        return _extract(data, expires)

    async def get_by_telegram_id(self, telegram_id: int) -> dict | None:
        """Найти пользователя по стабильному имени, которое создаёт бот.

        Отдельного маршрута ``by-telegram-id`` в Remnawave 2.8 нет. Имя
        ``tg<id>`` уникально и не содержит пользовательских данных кроме уже
        известного Telegram ID.
        """
        try:
            data = await self._request(
                "GET",
                EP_USER_BY_USERNAME.format(username=f"tg{telegram_id}"),
            )
        except PanelError:
            return None
        return data or None

    async def extend(
        self, user_id: str, *, days: int, devices: int
    ) -> tuple[str, str, str]:
        """Продлить подписку средствами самой панели.

        Action ``extend`` сам прибавляет дни к активному сроку, а для истёкшего
        считает от текущего момента. После него отдельным PATCH включаем ранее
        отключённого планировщиком пользователя и обновляем HWID-лимит.
        """
        numeric_id = _numeric_id(user_id)
        extended = await self._request(
            "POST",
            EP_EXTEND.format(user_id=numeric_id),
            json={"days": days},
        )
        body = {
            "id": numeric_id,
            "status": "ACTIVE",
            "hwidDeviceLimit": devices,
        }
        data = await self._request("PATCH", EP_USERS, json=body)
        expires = data.get("expireAt") or extended.get("expireAt")
        if not expires:
            raise PanelError("После продления панель не вернула expireAt")
        return _extract(data, expires, fallback_id=str(numeric_id))

    async def disable(self, user_id: str) -> None:
        numeric_id = _numeric_id(user_id)
        await self._request("POST", EP_DISABLE.format(user_id=numeric_id))


# ----------------------------------------------------------------------


def _expires_at(days: int) -> str:
    return (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    ).isoformat(timespec="seconds")


def _numeric_id(value: str | int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PanelError(
            f"В базе сохранён старый идентификатор панели {value!r}, нужен числовой id"
        ) from exc


def _extract(
    data: dict, expires: str, fallback_id: str | None = None
) -> tuple[str, str, str]:
    """Достать числовой id и ссылку на подписку из ответа панели.

    Ссылку панель отдаёт сама и она указывает на SUB_HOST — то есть на домен
    подписки, а не на домен сайта. Собирать её здесь руками нельзя: домен
    подписки живёт в конфиге панели, и две копии этого знания разъедутся.
    """
    user_id = data.get("id") or fallback_id
    sub_url = data.get("subscriptionUrl") or data.get("subscription_url")

    if user_id is None or not sub_url:
        raise PanelError(
            f"В ответе панели нет id или ссылки на подписку. Ключи: {sorted(data)}"
        )
    return str(user_id), sub_url, data.get("expireAt") or expires
