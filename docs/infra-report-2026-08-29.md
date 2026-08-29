# Khilios VPN — итоговый отчёт по production-инфраструктуре

Дата: 29.08.2026 (Europe/Moscow)

## Результат

Production восстановлен и проверен полным клиентским маршрутом. Все восемь
подключений из действующей подписки успешно прошли через настоящий Xray-клиент:
получили внешний IP, открыли `telegram.org` и получили HTTP-ответ Telegram API.
Проверка повторена после перезапуска нод и после перевода Hosts на доменные
имена.

Главная причина прежнего отказа найдена не в портах: Reality маскировался под
`www.microsoft.com`, чей TLS-ответ с текущим Xray 26.7.28 обрывал рукопожатие.
Все пять Reality-inbound и восемь Hosts переведены на проверенную цель
`www.cloudflare.com`. UUID пользователей, ключи, short ID и сроки подписок не
менялись.

## Ноды и мобильный интернет

| Приоритет | Локация | Основной канал | Резервный канал | Домен |
| --- | --- | --- | --- | --- |
| 1 | 🇫🇮 Финляндия | Reality, TCP 443 | XHTTP, TCP 8443 | `fi1.quietmesh.ru` |
| 2 | 🇩🇪 Германия | Reality, TCP 443 | XHTTP, TCP 8443 | `de1.quietmesh.ru` |
| 3 | 🇸🇪 Швеция | Reality, TCP 4443 | XHTTP, TCP 8443 | `se1.quietmesh.ru` |
| 4 | 🇳🇱 Нидерланды | Reality, TCP 9443 | XHTTP, TCP 10443 | `nl1.quietmesh.ru` |

Шведский 443 занят действующим `amnezia-openvpn-cloak`, нидерландский 443 —
Caddy. Эти два порта не освобождались ценой поломки других production-сервисов.

На всех четырёх нодах:

- `remnawave/node:3.2.2` работает;
- MSS clamp активен;
- BBR/fq и сетевой тюнинг применены;
- репозиторий обновлён до `65c195a`;
- служебный порт ноды доступен только панели.

На Швеции были найдены повреждённые бинарники Python и Docker. Пакеты
переустановлены из Ubuntu-репозитория, проверки `dpkg`, Docker и повторный
`deploy-node.sh` завершились успешно.

## DNS

Куплен и зарегистрирован `quietmesh.ru`. Созданы A-записи с TTL 60:

- `fi1.quietmesh.ru`;
- `de1.quietmesh.ru`;
- `se1.quietmesh.ru`;
- `nl1.quietmesh.ru`.

Cloudflare DNS разрешает все четыре записи в правильные адреса. В подписке
каждое имя используется двумя Hosts — основным и резервным. Старые
`panel.khilios.net` и `sub.khilios.net` уже возвращают NXDOMAIN; удалять там
больше нечего. Рабочие `panel.basaltworks.ru` и `sub.basaltworks.ru` сохранены.

## Remnawave и Happ

- Четыре отключённых Shadowsocks Host удалены через API после свежего дампа.
- В подписке осталось ровно 8 VLESS Host, Shadowsocks — 0.
- Порядок: четыре «мобильный интернет», затем четыре «резервный канал».
- Заголовок подписки — `khilios`.
- Описание сообщает об авариях и ведёт в `@khilios_vpn_bot`.
- Xray JSON и sing-box шаблоны получили routing-фрагменты из репозитория;
  существующие `inbounds`, `outbounds` и служебные поля сохранены.
- HWID-ограничение отключено: за последние 48 часов в логах нет отказов по
  устройствам. В базе девять пользователей с HWID, максимум два устройства.

Перед изменениями сохранён дамп
`/root/khilios-backups/remnawave-20260828T214658Z-templates.dump`. Временный
API-токен обслуживания удалён и из базы, и с диска.

## Бот, оплата и сайт

- `khilios-bot` пересобран из актуального `main` и работает.
- Polling `@khilios_vpn_bot`, Remnawave API и ЮKassa API запускаются без
  критических ошибок.
- В кабинете ЮKassa настроен `payment.succeeded` на
  `https://sub.basaltworks.ru/pay/webhook/yookassa`.
- Обработчик не доверяет телу webhook: статус и сумму платежа повторно проверяет
  через API ЮKassa, выдача срока идемпотентна.
- `STATUS_URL=https://sub.basaltworks.ru/status/status.json` добавлен в Vercel
  как Config-переменная для Production, Preview и Development.
- Production redeploy `dpl_A5PsT6XJ7K52g1mU5SaaeuwFcztt` завершён со статусом
  READY; `https://khilios.net/api/status` отдаёт HTTP 200 и четыре живые ноды.

## SSH и секреты

На DE, FI, SE и NL/panel:

- SSH слушает только TCP 2202;
- TCP 22 не слушается и удалён из UFW;
- вход root разрешён только по ключу (`prohibit-password`);
- `PasswordAuthentication no`, `KbdInteractiveAuthentication no`;
- root-пароли заменены случайными значениями, которые не выводились и не
  сохранялись;
- отдельный вход по ключу на 2202 проверен до закрытия 22.

В `node.env` DE/FI/SE сохранён `SSH_PORT=2202`, чтобы следующий идемпотентный
деплой не открыл 22 снова.

## Осталось вручную

1. Токен `@khilios_vpn_bot` ранее попадал в чат. Его нужно отозвать в
   `@BotFather` и выдать новый. Telegram Web на рабочем компьютере авторизован,
   однако `@BotFather` в открытом аккаунте отвечает `You don't have any bots
   yet`: этот аккаунт не является владельцем бота. Для ротации нужно войти в
   Telegram-аккаунт, с которого создавался `@khilios_vpn_bot`. Новый токен
   нельзя присылать в чат: его следует сразу записать в
   `/opt/khilios/infra/bot/bot.env`, затем пересобрать бот.
2. Серверная проверка не может гарантировать прохождение фильтрации каждого
   российского оператора. Нужна короткая приёмка с реального телефона без
   Wi-Fi минимум на MTS, МегаФон, Билайн и T2: основной канал, резервный XHTTP,
   Telegram и повторное подключение после сна приложения.

Локальные пользовательские файлы `.gitignore`,
`docs/growth-2026-08-26.md` и каталог `marketing/` не изменялись и в коммит не
включались.

## Финальная контрольная проверка

- `https://khilios.net/` — HTTP 200;
- `https://khilios.net/api/status` — HTTP 200, DE/FI/SE/NL в состоянии `up`;
- на всех четырёх серверах Remnawave Node `3.2.2` работает, MSS clamp активен;
- SSH 2202 доступен по ключу, TCP 22 не слушается;
- `khilios-bot` работает без перезапусков, Telegram API подтверждает
  `@khilios_vpn_bot`, в свежих логах нет `Unauthorized`, `Conflict`,
  `Critical` или `Traceback`.
