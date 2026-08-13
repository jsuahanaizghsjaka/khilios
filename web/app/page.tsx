import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { PLANS, SERVICE } from "@/lib/config";
import { BotLink, LandingInteractive } from "./landing-interactive";

export const metadata: Metadata = {
  title: "Защищённое соединение без настройки",
  description:
    "Один бот, одна кнопка, ключ пришёл. Семь дней бесплатно, без карты и автосписаний.",
};

const FACTS = [
  {
    title: "Статус узлов открыт",
    text: "Показываем состояние и время последней проверки. Если данные устарели, прямо об этом говорим.",
  },
  {
    title: "О сбоях пишем сами",
    text: "Не прячемся за «техническими работами»: сообщаем, что случилось и когда рассчитываем исправить.",
  },
  {
    title: "Возврат без уговоров",
    text: "Возвращаем стоимость неиспользованных дней по первому запросу. Причину спрашивать не будем.",
  },
  {
    title: "Банки и Госуслуги — напрямую",
    text: "Российские сервисы обходят туннель по готовым правилам маршрутизации и работают с вашим обычным адресом.",
  },
  {
    title: "Без лимита трафика",
    text: "Не режем скорость после определённого объёма. Фактическая скорость зависит от сети, устройства и выбранного узла.",
  },
  {
    title: "Несколько способов подключения",
    text: "Предлагаем совместимые приложения и ручную настройку. Доступность конкретного приложения в магазине не гарантируем.",
  },
];

const STEPS = [
  ["1", "Открыть бота", "Вход через Telegram — без анкет и подтверждения почты."],
  ["2", "Забрать ключ", "Семь дней бесплатно. Карта для пробного периода не нужна."],
  ["3", "Поставить приложение", "Бот даст ссылку и добавит настройки в совместимый клиент."],
  ["4", "Включить", "На телефоне и компьютере — одной кнопкой. Совместимый роутер можно настроить вручную."],
];

export default function Home() {
  return (
    <div className="landing">
      <div className="landing-bg" aria-hidden="true" />
      <div className="landing-orb" aria-hidden="true">
        <Image
          src="/sphere.gif"
          alt=""
          width={500}
          height={500}
          priority
          unoptimized
        />
      </div>

      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="landing-container landing-hero-inner">
          <p className="landing-overline">Khilios — защищённое соединение</p>
          <h1 id="hero-title">Защищённое соединение, которое не надо настраивать</h1>
          <p className="landing-lead">
            Один бот, одна кнопка, ключ пришёл. Разбираться в протоколах и
            конфигах не нужно — это наша работа, а не ваша.
          </p>
          <div className="landing-actions">
            <BotLink botUrl={SERVICE.bot} className="pill pill-primary" start="site_start">
              Попробовать 7 дней бесплатно
            </BotLink>
            <a href="#tariffs" className="pill pill-outline">Тарифы</a>
          </div>
          <p className="landing-note">
            Карту на пробный период не спрашиваем. Автосписания нет — ни на
            пробном, ни после него.
          </p>
        </div>
      </section>

      <div className="landing-ticker" aria-label="Основные условия">
        <div className="landing-ticker-track">
          {["7 дней бесплатно", "Без автосписаний", "Карта МИР, СБП, Stars и криптовалюта", "Банки и Госуслуги — напрямую", "Статус узлов открыт", "Возврат по первому запросу"].concat(
            ["7 дней бесплатно", "Без автосписаний", "Карта МИР, СБП, Stars и криптовалюта", "Банки и Госуслуги — напрямую", "Статус узлов открыт", "Возврат по первому запросу"],
          ).map((item, index) => (
            <span className="landing-ticker-item" key={`${item}-${index}`}>
              <span className="landing-dot" aria-hidden="true" />{item}
            </span>
          ))}
        </div>
      </div>

      <section id="status" className="landing-section landing-anchor" aria-labelledby="status-title">
        <div className="landing-container">
          <p className="landing-section-overline">— честно</p>
          <h2 id="status-title" className="landing-section-title">Что это значит на практике</h2>
          <div className="facts-grid">
            {FACTS.map((fact) => (
              <article className="landing-card" key={fact.title}>
                <h3>{fact.title}</h3>
                <p>{fact.text}</p>
              </article>
            ))}
          </div>
          <div className="status-promo">
            <div>
              <strong>Живые данные находятся на отдельной странице.</strong>
              <p>Она получает `status.json` от панели и обновляется раз в минуту.</p>
            </div>
            <Link href="/status" className="pill pill-outline">Открыть статус узлов</Link>
          </div>
        </div>
      </section>

      <section id="setup" className="landing-section landing-anchor" aria-labelledby="setup-title">
        <div className="landing-container">
          <p className="landing-section-overline">— подключение</p>
          <h2 id="setup-title" className="landing-section-title">Четыре коротких шага</h2>
          <div className="steps-grid">
            {STEPS.map(([number, title, text]) => (
              <article className="landing-step" key={number}>
                <span className="step-number">{number}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
          <LandingInteractive mode="nodes" />
        </div>
      </section>

      <section id="tariffs" className="landing-section landing-anchor" aria-labelledby="tariffs-title">
        <div className="landing-container">
          <p className="landing-section-overline">— тарифы</p>
          <h2 id="tariffs-title" className="landing-section-title">Платите за дни, а не за обещания</h2>
          <p className="landing-section-subtitle">
            Разные тарифы — одинаковые узлы и правила возврата. Передумали —
            вернём за оставшиеся дни.
          </p>
          <LandingInteractive botUrl={SERVICE.bot} plans={PLANS} mode="plans" />
        </div>
      </section>

      <section className="landing-section">
        <div className="landing-container landing-narrow">
          <p className="landing-section-overline">— честно</p>
          <h2 className="landing-section-title">Чего мы не обещаем</h2>
          <div className="honest-copy">
            <p>
              Что соединение будет работать всегда и везде. Сетевые условия
              меняются, а стопроцентная доступность не зависит от одного сервиса.
            </p>
            <p>
              Обещаем другое: не скрывать известные сбои, поддерживать запасные
              узлы и вернуть деньги за неиспользованные дни.
            </p>
            <p className="muted">
              Поддержка {SERVICE.supportHours}. {SERVICE.supportPromise}
              Приоритетной очереди в тарифах нет — правила ответа одинаковы для всех.
            </p>
          </div>
        </div>
      </section>

      <section className="landing-section landing-cta-section">
        <div className="landing-container landing-narrow">
          <div className="landing-cta">
            <h2>Проще один раз проверить на своих устройствах</h2>
            <p>
              Семь дней бесплатно, без карты и автоматического продления. Если
              подойдёт — выберите тариф в боте.
            </p>
            <div className="landing-actions">
              <BotLink botUrl={SERVICE.bot} className="pill pill-primary" start="site_final">
                Начать пробный период
              </BotLink>
              <Link href="/status" className="pill pill-outline">Статус узлов</Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
