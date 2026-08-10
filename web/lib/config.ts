// Единственное место, где живут цены, ссылки и расписание поддержки.
// Меняется здесь — меняется на всех страницах.

export const SERVICE = {
  name: "khilios",

  // Заполняется, когда бот и канал заведены (неделя 3 и 4 плана).
  bot: process.env.NEXT_PUBLIC_BOT_URL ?? "",
  channel: process.env.NEXT_PUBLIC_CHANNEL_URL ?? "",

  // Своя страница оплаты, если она когда-нибудь появится. Пока пусто:
  // эквайринг на модерации (docs/payments.md), и платит человек в боте.
  pay: process.env.NEXT_PUBLIC_PAY_URL ?? "",

  // Написано на сайте намеренно. Люди нормально относятся к честному
  // расписанию и плохо — к молчанию. Круглосуточная поддержка одним
  // человеком заканчивается выгоранием, а не довольными пользователями.
  supportHours: "с 9:00 до 11:00 и с 19:00 до 22:00 МСК",
  supportPromise: "Отвечаем в течение двух часов внутри окна.",
};

export type Plan = {
  id: string;
  name: string;
  price: number;
  period: string;
  devices: number;
  note?: string;
  featured?: boolean;
};

// period — готовая строка для показа, а не единица измерения:
// подставлять предлог в шаблоне пришлось бы с исключением на пробный тариф.
export const PLANS: Plan[] = [
  {
    id: "trial",
    name: "Пробный",
    price: 0,
    period: "7 дней",
    devices: 1,
    note: "Без карты и без автосписания. Карту вообще не спрашиваем.",
  },
  {
    id: "basic",
    name: "Базовый",
    price: 199,
    period: "в месяц",
    devices: 2,
  },
  {
    id: "standard",
    name: "Стандарт",
    price: 299,
    period: "в месяц",
    devices: 5,
    featured: true,
  },
  {
    id: "year",
    name: "Год",
    price: 1990,
    period: "в год",
    devices: 5,
    note: "166 ₽ в месяц.",
  },
];

// Куда ведёт кнопка тарифа.
//
// По умолчанию — в бота, потому что оплата живёт там: свой эквайринг ещё
// на модерации (docs/payments.md). Выбранный тариф уходит вместе со
// ссылкой: без этого человек, уже нажавший «Стандарт» на сайте, выбирает
// его второй раз в переписке — самое дорогое место, где отваливаются.
//
// Появится своя страница оплаты — задаётся NEXT_PUBLIC_PAY_URL, и кнопки
// уходят на неё. Менять код и разметку при этом не придётся.
//
// Пусто и то и другое — вызывающий код показывает «Скоро открытие».
export function checkoutLink(planId?: string): string {
  if (SERVICE.pay) {
    const sep = SERVICE.pay.includes("?") ? "&" : "?";
    return planId ? `${SERVICE.pay}${sep}plan=${planId}` : SERVICE.pay;
  }

  if (!SERVICE.bot || !planId) return SERVICE.bot;

  // Deep link Telegram: ровно один параметр start, значение — латиница,
  // цифры, дефис и подчёркивание, до 64 символов. Всё остальное клиент
  // молча отбрасывает, поэтому чужие query-параметры из ссылки срезаем.
  const base = SERVICE.bot.split("?")[0].replace(/\/+$/, "");
  return `${base}?start=plan_${planId}`;
}

export const REFUND_DAYS_RULE =
  "Возвращаем пропорционально неиспользованным дням, по первому запросу, без выяснения причин.";
