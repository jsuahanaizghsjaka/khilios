import type { Metadata } from "next";
import { SignIn } from "@clerk/nextjs";
import { AuthUnavailable } from "@/app/auth-unavailable";
import { isAuthConfigured } from "@/lib/auth-config";

export const metadata: Metadata = {
  title: "Вход",
  description: "Вход в личный кабинет Khilios.",
};

export default function SignInPage() {
  if (!isAuthConfigured()) return <AuthUnavailable />;

  return (
    <section className="auth-page" aria-labelledby="sign-in-title">
      <div className="auth-copy">
        <p className="eyebrow">Личный кабинет</p>
        <h1 id="sign-in-title">С возвращением</h1>
        <p className="lead">
          Войдите, чтобы открыть профиль и настройки безопасности.
        </p>
      </div>
      <div className="auth-widget">
        <SignIn
          path="/sign-in"
          signUpUrl="/sign-up"
          fallbackRedirectUrl="/account"
        />
      </div>
    </section>
  );
}
