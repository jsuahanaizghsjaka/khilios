import Link from "next/link";
import { PLANS, SERVICE, checkoutLink } from "@/lib/config";
import { devices } from "@/lib/plural";

// Карточки тарифов нужны и на главной, и на странице тарифов. Разметка
// была скопирована в оба места и уже начала расходиться, поэтому живёт
// здесь одна.
//
// Кнопка есть у каждого тарифа, а не одна общая внизу: человек выбирает
// не «купить вообще», а конкретный срок, и нажать он хочет там, где смотрит.

export function PlanCards() {
  // Ссылка живая, только когда заведён бот или страница оплаты. Пока нет —
  // показываем заглушку вместо ссылки в никуда: неработающая кнопка на
  // странице тарифов выглядит хуже, чем честное «скоро».
  const live = Boolean(checkoutLink());

  return (
    <ul className="plans">
      {PLANS.map((plan) => {
        const trial = plan.price === 0;

        return (
          <li
            key={plan.id}
            className={plan.featured ? "plan plan--featured" : "plan"}
          >
            {plan.featured && <span className="tag">Обычно берут этот</span>}
            <h3>{plan.name}</h3>

            <div className="price">
              {/* 1 990 ₽ читается быстрее, чем 1990 ₽ */}
              {trial ? "Бесплатно" : `${plan.price.toLocaleString("ru-RU")} ₽`}
              <span className="period">{plan.period}</span>
            </div>

            <p className="devices">
              {plan.devices} {devices(plan.devices)}
            </p>

            {plan.note && <p className="note">{plan.note}</p>}

            {/* Прижата к низу карточки, чтобы кнопки в ряду стояли на одной
                линии, даже когда у тарифов разное количество текста. */}
            <div className="plan-foot">
              {live ? (
                <Link
                  className={plan.featured ? "btn" : "btn btn--ghost"}
                  href={checkoutLink(plan.id)}
                >
                  {trial ? "Начать бесплатно" : "Выбрать"}
                </Link>
              ) : (
                <span className="btn" aria-disabled="true">
                  Скоро открытие
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// Подпись под карточками: куда именно ведёт кнопка. Человек имеет право
// знать, что сейчас откроется Telegram, до того как нажмёт.
export function PlanCaption() {
  if (!SERVICE.bot || SERVICE.pay) return null;

  return (
    <p className="small muted">
      Кнопка открывает бота в Telegram — там же проходит оплата картой МИР или
      через СБП.
    </p>
  );
}
