import type { Metadata } from "next";
import { SignOutButton } from "@clerk/nextjs";
import { auth, currentUser } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthUnavailable } from "@/app/auth-unavailable";
import { isAuthConfigured } from "@/lib/auth-config";
import { SERVICE } from "@/lib/config";

export const metadata: Metadata = {
  title: "Личный кабинет",
  description: "Профиль и настройки аккаунта Khilios.",
};

function formatDate(timestamp: number | null) {
  if (!timestamp) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/Moscow",
  }).format(new Date(timestamp));
}

export default async function AccountPage() {
  if (!isAuthConfigured()) return <AuthUnavailable />;

  const { userId } = await auth();
  if (!userId) redirect("/sign-in?redirect_url=%2Faccount");

  const user = await currentUser();
  if (!user) redirect("/sign-in?redirect_url=%2Faccount");

  const email = user.primaryEmailAddress?.emailAddress || "Адрес не указан";
  const name = user.fullName || user.firstName || email;

  return (
    <section className="account-page" aria-labelledby="account-title">
      <div className="account-heading">
        <div>
          <p className="eyebrow">Личный кабинет</p>
          <h1 id="account-title">Здравствуйте, {name}</h1>
          <p className="lead">
            Здесь находятся данные аккаунта и быстрый переход к управлению
            подпиской.
          </p>
        </div>
        <SignOutButton redirectUrl="/">
          <button type="button" className="btn btn--ghost">
            Выйти
          </button>
        </SignOutButton>
      </div>

      <div className="account-grid">
        <article className="account-card">
          <p className="account-card-label">Аккаунт</p>
          <h2>Профиль</h2>
          <dl className="account-details">
            <div>
              <dt>Имя</dt>
              <dd>{name}</dd>
            </div>
            <div>
              <dt>Почта</dt>
              <dd>{email}</dd>
            </div>
            <div>
              <dt>Регистрация</dt>
              <dd>{formatDate(user.createdAt)}</dd>
            </div>
          </dl>
          <Link className="account-link" href="/account/profile">
            Изменить профиль и безопасность
          </Link>
        </article>

        <article className="account-card account-card-accent">
          <p className="account-card-label">Подписка</p>
          <h2>Управление в Telegram</h2>
          <p>
            Тариф, ключ, продление и оставшийся срок пока находятся в боте —
            там же проходят платежи и выдаётся конфигурация.
          </p>
          {SERVICE.bot ? (
            <a
              className="btn"
              href={SERVICE.bot}
              target="_blank"
              rel="noopener noreferrer"
            >
              Открыть бота
            </a>
          ) : (
            <span className="btn" aria-disabled="true">
              Бот скоро откроется
            </span>
          )}
        </article>

        <article className="account-card account-card-wide">
          <p className="account-card-label">Безопасность</p>
          <h2>Пароль, устройства и активные сессии</h2>
          <p>
            В разделе профиля можно сменить пароль, проверить способы входа и
            завершить незнакомые сессии. Секреты авторизации не хранятся в коде
            сайта или в браузерном хранилище.
          </p>
          <Link className="btn btn--ghost" href="/account/profile">
            Открыть настройки
          </Link>
        </article>
      </div>
    </section>
  );
}
