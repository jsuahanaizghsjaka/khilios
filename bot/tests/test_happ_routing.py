"""Профиль «только Telegram через VPN».

Проверяется в основном форма: ошибка здесь не падает и не логируется —
Happ просто молча не примет профиль, а мы узнаем об этом от пользователя
через неделю. Поэтому структура ссылки и содержимое профиля фиксируются
тестом, а не глазами.
"""

from __future__ import annotations

import base64
import json

from app import happ_routing, keyboards as kb


def _decode(link: str) -> dict:
    prefix = "happ://routing/add/"
    assert link.startswith(prefix)
    return json.loads(base64.b64decode(link[len(prefix):]).decode())


def test_deep_link_decodes_back_to_profile():
    assert _decode(happ_routing.deep_link()) == happ_routing.profile()


def test_profile_does_not_hijack_all_traffic():
    """Суть режима: глобальный прокси выключен, иначе профиль «только
    Telegram» уводил бы в туннель вообще всё и отличался от основного
    ровно ничем."""
    profile = happ_routing.profile()
    assert profile["GlobalProxy"] == "false"
    assert profile["DirectSites"] == []
    assert profile["DirectIp"] == []


def test_profile_routes_telegram_by_name_and_by_address():
    """Одних доменов мало: клиент Telegram ходит к своим DC прямо по IP,
    и без списка подсетей эти соединения уйдут мимо туннеля."""
    profile = happ_routing.profile()
    assert "domain:t.me" in profile["ProxySites"]
    assert "domain:telegram.org" in profile["ProxySites"]
    assert "149.154.160.0/20" in profile["ProxyIp"]
    assert any(":" in cidr for cidr in profile["ProxyIp"])  # IPv6 не забыт


def test_profile_resolves_telegram_names_through_tunnel():
    """Резолвинг у провайдера отдал бы подменённый адрес, и правила
    маршрутизации сработали бы уже для неверного IP."""
    profile = happ_routing.profile()
    assert profile["RemoteDNSType"] == "DoH"
    assert profile["RemoteDNSDomain"].startswith("https://")


def test_profile_name_is_stable():
    """Happ обновляет профиль с тем же именем вместо создания второго.
    Плавающее имя означало бы десяток «Telegram (2)» у постоянного клиента."""
    assert happ_routing.profile()["Name"] == "Telegram"


def test_profile_is_json_serialisable_without_surprises():
    # Ошибка сериализации здесь всплыла бы только в проде, при нажатии кнопки.
    json.dumps(happ_routing.profile(), ensure_ascii=False)


def test_button_url_points_at_our_host():
    assert (
        kb.happ_telegram_url("sub.example.net")
        == "https://sub.example.net/pay/happ/telegram"
    )
