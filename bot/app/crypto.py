"""Оплата криптовалютой через @CryptoBot (Crypto Pay API).

Отличается от остальных способов принципиально, и это определяет всю
конструкцию: Stars и ЮKassa приходят готовым событием `successful_payment`
от самого Telegram, а здесь оплата происходит в чужом боте, и узнать о ней
можно только спросив.

Спрашиваем опросом, а не вебхуком. Вебхук требует открытого наружу HTTPS
на машине, где лежит база всех пользователей и ключи, — тот же размен, от
которого отказались в пользу long polling для самого бота.

ПОЧЕМУ СЧЁТ НЕ СЧИТАЕТСЯ ОПЛАЧЕННЫМ, ПОКА НЕ СПРОСИЛИ У API.
Ссылку на оплату видит пользователь, и статус в ней тоже. Верить клиенту
здесь нельзя ни в каком виде: подтверждение оплаты берётся только из
ответа API по идентификатору счёта, который выдали мы.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

MAINNET = "https://pay.crypt.bot/api"
TESTNET = "https://testnet-pay.crypt.bot/api"


class CryptoError(Exception):
    """API ответило отказом. Повторять бессмысленно."""


class CryptoUnavailable(Exception):
    """API недоступно. Повторить имеет смысл."""


class CryptoClient:
    def __init__(self, token: str, *, testnet: bool = False, timeout: float = 15.0) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=TESTNET if testnet else MAINNET,
            headers={"Crypto-Pay-API-Token": token},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, **params) -> dict:
        try:
            resp = await self._client.get(f"/{method}", params=params)
        except httpx.RequestError as exc:
            raise CryptoUnavailable(f"{method}: {exc}") from exc

        if resp.status_code >= 500:
            raise CryptoUnavailable(f"{method}: {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise CryptoUnavailable(f"{method}: ответ не JSON") from exc

        if not payload.get("ok"):
            raise CryptoError(f"{method}: {payload.get('error')}")

        return payload.get("result") or {}

    async def ping(self) -> bool:
        """Принят ли токен. Вызывается на старте, чтобы неверный токен
        обнаружился в логе, а не на первом человеке с деньгами."""
        try:
            await self._call("getMe")
            return True
        except (CryptoError, CryptoUnavailable) as exc:
            log.error("Crypto Pay недоступен или токен не принят: %s", exc)
            return False

    async def create_invoice(
        self, *, amount_rub: int, plan_id: str, telegram_id: int
    ) -> tuple[str, str]:
        """Создать счёт. Возвращает (invoice_id, ссылка на оплату).

        Сумма выставляется в рублях с конвертацией на стороне сервиса
        (`fiat` + `currency_type=fiat`): курс считает он в момент оплаты.
        Считать курс самим значило бы держать у себя ещё один источник
        цены, который разъедется с рублёвым.
        """
        result = await self._call(
            "createInvoice",
            currency_type="fiat",
            fiat="RUB",
            amount=str(amount_rub),
            description=f"khilios — {plan_id}",
            # payload возвращается нам вместе со счётом: по нему выдаём
            # тариф, не доверяя ни сумме, ни словам пользователя.
            payload=f"{telegram_id}:{plan_id}",
            allow_comments="false",
            allow_anonymous="false",
            expires_in=3600,
        )

        invoice_id = result.get("invoice_id")
        url = result.get("bot_invoice_url") or result.get("pay_url")

        if not invoice_id or not url:
            raise CryptoError(f"В ответе нет счёта или ссылки: {sorted(result)}")

        return str(invoice_id), url

    async def paid_invoice_ids(self, invoice_ids: list[str]) -> set[str]:
        """Какие из этих счетов оплачены.

        Спрашиваем пачкой: счетов немного, а отдельный запрос на каждый —
        это лимиты API на ровном месте.
        """
        if not invoice_ids:
            return set()

        result = await self._call(
            "getInvoices", invoice_ids=",".join(invoice_ids), status="paid"
        )
        items = result.get("items") or []
        return {str(i.get("invoice_id")) for i in items if i.get("invoice_id")}
