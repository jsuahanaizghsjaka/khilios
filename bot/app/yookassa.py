"""Оплата картой и через СБП напрямую через ЮKassa (веб-чекаут).

Отличается от Telegram Payments принципиально: там форму оплаты рисует сам
Telegram и провайдеру нужен только provider_token из BotFather. Здесь форму
рисует ЮKassa на своей странице, и с ней нужно говорить напрямую — создавать
платёж через API и узнавать его судьбу.

────────────────────────────────────────────────────────────────────────
ГЛАВНОЕ РЕШЕНИЕ ЭТОГО МОДУЛЯ: ВЕБХУКУ НЕ ВЕРИМ, ПЕРЕСПРАШИВАЕМ API.

У вебхуков ЮKassa нет подписи, которую можно проверить без похода в их же
API за списком ключей. Официальная рекомендация ЮKassa на этот случай —
не доверять телу уведомления, а по payment_id из него запросить актуальный
статус через GET /v3/payments/{id}. Так подделанный вебхук с чужим сервера
не может провести оплату: чтобы получить status=succeeded, атакующему
нужно, чтобы ЮKassa сама подтвердила платёж по своему payment_id, а не
просто прислать желаемый JSON на наш адрес.

Тот же принцип уже применён к криптоплатежам в crypto.py: там платёж тоже
подтверждается запросом к API, а не телом ответа от пользователя или
стороннего сервиса.
────────────────────────────────────────────────────────────────────────

VERIFY: структура ответа /v3/payments сверена с документацией ЮKassa на
момент написания. Проверить перед первым живым платежом — она меняется.
"""

from __future__ import annotations

import logging
import uuid

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.yookassa.ru/v3"


class YooKassaError(Exception):
    """API ответило отказом. Повторять с теми же параметрами бессмысленно."""


class YooKassaUnavailable(Exception):
    """API недоступно. Повторить имеет смысл."""


class YooKassaClient:
    def __init__(self, shop_id: str, secret_key: str, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            auth=(shop_id, secret_key),
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise YooKassaUnavailable(f"{method} {path}: {exc}") from exc

        if resp.status_code >= 500:
            raise YooKassaUnavailable(f"{method} {path}: {resp.status_code}")
        if resp.status_code >= 400:
            raise YooKassaError(f"{method} {path}: {resp.status_code} {resp.text[:400]}")

        return resp.json()

    async def ping(self) -> bool:
        """Приняты ли shop_id/secret_key.

        ЮKassa не даёт отдельного health-эндпоинта — используем список
        платежей с нулевым лимитом: он требует валидной авторизации и не
        создаёт побочных эффектов.
        """
        try:
            await self._request("GET", "/payments", params={"limit": 1})
            return True
        except (YooKassaError, YooKassaUnavailable) as exc:
            log.error("ЮKassa недоступна или ключи не приняты: %s", exc)
            return False

    async def create_payment(
        self,
        *,
        order_id: str,
        amount_rub: int,
        plan_name: str,
        return_url: str,
    ) -> tuple[str, str]:
        """Создать платёж. Возвращает (yk_payment_id, ссылка на оплату).

        confirmation.type=redirect — пользователь уходит на страницу ЮKassa
        и возвращается по return_url после оплаты. Свою форму ввода карты
        не рисуем и не будем: это требует PCI DSS-сертификации, а ЮKassa
        уже её имеет и уже умеет показывать карту, СБП и что там ещё
        подключено в личном кабинете — переизобретать это себе дороже
        в буквальном смысле.

        Idempotence-Key = order_id: повторный вызов с тем же order_id
        (например, если ответ не дошёл и хендлер вызвался снова) не создаст
        второй платёж на ту же сумму, а вернёт первый.
        """
        body = {
            "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": f"khilios — {plan_name}",
            # metadata возвращается нам в ответе на GET, но не является
            # источником истины о заказе: order_id уже есть в нашей базе,
            # это поле — только для быстрой сверки глазами в личном кабинете.
            "metadata": {"order_id": order_id},
        }

        data = await self._request(
            "POST",
            "/payments",
            json=body,
            headers={"Idempotence-Key": order_id},
        )

        yk_id = data.get("id")
        url = (data.get("confirmation") or {}).get("confirmation_url")

        if not yk_id or not url:
            raise YooKassaError(f"В ответе нет id или confirmation_url: {sorted(data)}")

        return yk_id, url

    async def get_payment_status(self, yk_payment_id: str) -> str:
        """Актуальный статус платежа. Единственный источник истины —
        см. предупреждение в шапке модуля.

        VERIFY: значения статуса — pending / waiting_for_capture / succeeded
        / canceled, по документации ЮKassa на момент написания.
        """
        data = await self._request("GET", f"/payments/{yk_payment_id}")
        status = data.get("status")
        if not status:
            raise YooKassaError(f"В ответе нет status: {sorted(data)}")
        return status


def new_order_id() -> str:
    """order_id генерируется у нас, а не берётся из yk_payment_id: он нужен
    до создания платежа — чтобы Idempotence-Key был готов заранее и повторный
    клик по кнопке «Оплатить» не породил два платежа."""
    return uuid.uuid4().hex
