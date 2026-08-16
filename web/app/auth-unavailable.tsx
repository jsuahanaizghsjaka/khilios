import Link from "next/link";

export function AuthUnavailable() {
  return (
    <section className="auth-page" aria-labelledby="auth-unavailable-title">
      <div className="auth-copy">
        <p className="eyebrow">Личный кабинет</p>
        <h1 id="auth-unavailable-title">Вход временно недоступен</h1>
        <p className="lead">
          Интерфейс кабинета уже установлен, но провайдер авторизации ещё не
          подключён к этому окружению. Подпиской по-прежнему можно управлять в
          Telegram-боте.
        </p>
        <div className="btn-row">
          <Link className="btn" href="/">
            На главную
          </Link>
        </div>
      </div>
    </section>
  );
}
