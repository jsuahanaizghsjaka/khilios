import Link from "next/link";
import type { Metadata } from "next";
import { SERVICE, PLANS, REFUND_DAYS_RULE } from "@/lib/config";
import { devices } from "@/lib/plural";

export const metadata: Metadata = { title: "Тарифы" };

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
        <li>Оплата картой МИР и через СБП.</li>
      </ul>

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
