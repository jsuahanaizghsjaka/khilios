import type { Metadata } from "next";
import { SignUp } from "@clerk/nextjs";
import { AuthUnavailable } from "@/app/auth-unavailable";
import { isAuthConfigured } from "@/lib/auth-config";

export const metadata: Metadata = {
  title: "Регистрация",
  description: "Регистрация личного кабинета Khilios.",
};

export default function SignUpPage() {
  if (!isAuthConfigured()) return <AuthUnavailable />;

  return (
    <section className="auth-page" aria-labelledby="sign-up-title">
      <div className="auth-copy">
        <p className="eyebrow">Новый аккаунт</p>
        <h1 id="sign-up-title">Создать личный кабинет</h1>
        <p className="lead">
          Регистрация нужна только для профиля. Пробный период остаётся без
          карты и автоматического продления.
        </p>
      </div>
      <div className="auth-widget">
        <SignUp
          path="/sign-up"
          signInUrl="/sign-in"
          fallbackRedirectUrl="/account"
        />
      </div>
    </section>
  );
}
