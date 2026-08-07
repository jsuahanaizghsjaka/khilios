// Единственное место, где живут цены, ссылки и расписание поддержки.
// Меняется здесь — меняется на всех страницах.

export const SERVICE = {
  name: "khilios",

  // Заполняется, когда бот и канал заведены (неделя 3 и 4 плана).
  bot: process.env.NEXT_PUBLIC_BOT_URL ?? "",
  channel: process.env.NEXT_PUBLIC_CHANNEL_URL ?? "",

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

export const REFUND_DAYS_RULE =
  "Возвращаем пропорционально неиспользованным дням, по первому запросу, без выяснения причин.";
