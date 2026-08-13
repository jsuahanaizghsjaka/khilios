import Link from "next/link";
import type { Metadata } from "next";
import { SERVICE, PLANS, REFUND_DAYS_RULE } from "@/lib/config";

export const metadata: Metadata = { title: "Тарифы" };

// 1 устройство, 2 устройства, 5 устройств — правило с двумя переломами,
// а не одним. Простое «один или много» даёт «2 устройств».
function devices(n: number): string {
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod100 >= 11 && mod100 <= 14) return "устройств";
  if (mod10 === 1) return "устройство";
  if (mod10 >= 2 && mod10 <= 4) return "устройства";
  return "устройств";
}

export default function Tariffs() {
  return (
    <>
      <h1>Тарифы</h1>

      <p className="lead">
        Без скрытых списаний и без «пробного за 10 ₽, а потом сюрприз».
      </p>

      <ul className="plans">
        {PLANS.map((plan) => (
          <li
            key={plan.id}
            className={plan.featured ? "plan plan--featured" : "plan"}
          >
            {plan.featured && <span className="tag">Обычно берут этот</span>}
            <h3>{plan.name}</h3>
            <div className="price">
              {/* 1 990 ₽ читается быстрее, чем 1990 ₽ */}
              {plan.price === 0
                ? "Бесплатно"
                : `${plan.price.toLocaleString("ru-RU")} ₽`}
              <span className="period">{plan.period}</span>
            </div>
            <p className="devices">
              {plan.devices} {devices(plan.devices)}
            </p>
            {plan.note && <p className="note">{plan.note}</p>}
          </li>
        ))}
      </ul>

      <div className="btn-row">
        {SERVICE.bot ? (
          <Link className="btn" href={SERVICE.bot}>
            Начать с пробного периода
          </Link>
        ) : (
          <span className="btn" aria-disabled="true">
            Скоро открытие
          </span>
        )}
      </div>

      <h2>Что входит в любой тариф</h2>

      <ul className="reasons">
        <li>Безлимитный трафик, скорость не режем.</li>
        <li>
          Российские сайты, банки, Госуслуги и маркетплейсы идут напрямую —
          настраивать ничего не нужно, это работает сразу.
        </li>
        <li>
          Несколько приложений на выбор. Если одно уберут из магазина, у вас
          останется запасное.
        </li>
        <li>
          Четыре способа оплаты: карта МИР, СБП, Telegram Stars и
          криптовалюта.
        </li>
      </ul>

      <h2>Как платить</h2>

      <ul className="reasons">
        <li>
          <strong>Карта МИР и СБП.</strong> Обычная оплата в боте: жмёте
          кнопку, платите, ключ приходит сразу.
        </li>
        <li>
          <strong>Telegram Stars.</strong> Внутренняя валюта Telegram —
          удобно, если звёзды уже есть на счету.
        </li>
        <li>
          <strong>Криптовалюта.</strong> Через официальный кошелёк в
          Telegram. Курс считает он сам, ключ приходит автоматически после
          подтверждения перевода.
        </li>
      </ul>

      <p className="small muted">
        Автосписания нет ни при одном способе. Карта не запоминается, продление
        — только вашей кнопкой.
      </p>

      <h2>Про устройства</h2>

      <p>
        Лимит честный: пять устройств — это пять устройств. Мы не обещаем
        «безлимит», потому что один ключ, разошедшийся по чату на сорок
        человек, кладёт узел для всех остальных. Ограничение здесь ради того,
        чтобы у вас работало.
      </p>

      <h2>Про возврат</h2>

      <p>{REFUND_DAYS_RULE}</p>

      <p className="small">
        Подробности — в <Link href="/legal/refund">условиях возврата</Link> и{" "}
        <Link href="/legal/offer">оферте</Link>.
      </p>
    </>
  );
}
