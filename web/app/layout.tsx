import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { ruRU } from "@clerk/localizations";
import Image from "next/image";
import localFont from "next/font/local";
import Link from "next/link";
import { SERVICE } from "@/lib/config";
import { clerkPublishableKey, isAuthConfigured } from "@/lib/auth-config";
import { Nav } from "./nav";
import "./globals.css";

// Файлы лежат в репозитории: ни сборка, ни браузер пользователя не обращаются
// к Google Fonts. Это важно и для приватности, и для доступности из сетей,
// где внешний шрифтовой CDN может быть недоступен.
const manrope = localFont({
  src: "./fonts/Manrope-Variable.ttf",
  display: "swap",
  variable: "--font-sans",
  weight: "200 800",
});

// Моноширинный — для данных: имена узлов, время проверки, цены.
// Цифры в нём не «пляшут» между строками таблицы.
const mono = localFont({
  src: "./fonts/JetBrainsMono-Variable.ttf",
  display: "swap",
  variable: "--font-mono",
  weight: "100 800",
});

export const metadata: Metadata = {
  title: {
    default: SERVICE.name,
    template: `%s — ${SERVICE.name}`,
  },
  description:
    "Защищённое соединение, которое не надо настраивать. Статус узлов открыт, о сбоях пишем сами, деньги возвращаем без разговоров.",
  icons: {
    icon: "/logo.jpg",
    apple: "/logo.jpg",
  },
  // Поисковики сюда не нужны: продвижение таких сервисов в РФ запрещено
  // с марта 2024, и SEO в плане нет намеренно. Люди приходят из бота и канала.
  robots: { index: false, follow: false },
};

// Тема применяется до первой отрисовки, иначе страница моргает тёмным
// у тех, кто выбрал светлую. Скрипт намеренно крошечный и синхронный:
// всё, что он делает, — переносит сохранённый выбор на <html>.
const themeScript = `try{var t=localStorage.getItem('theme');document.documentElement.dataset.theme=t==='light'?'light':'dark'}catch(e){document.documentElement.dataset.theme='dark'}`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const authEnabled = isAuthConfigured();
  const content = (
    <>
      <header className="site-head">
        <div className="wrap">
          <Link href="/" className="brand">
            <Image
              src="/logo.jpg"
              alt=""
              width={38}
              height={38}
              className="brand-logo"
              priority
            />
            <span>{SERVICE.name}</span>
          </Link>
          <Nav authEnabled={authEnabled} />
        </div>
      </header>

      <main className="wrap">{children}</main>

      <footer className="site-foot">
        <div className="wrap">
          <nav aria-label="Правовая информация">
            <Link href="/legal/offer">Оферта</Link>
            <Link href="/legal/privacy">Конфиденциальность</Link>
            <Link href="/legal/refund">Возврат</Link>
            {SERVICE.channel && (
              <a
                href={SERVICE.channel}
                target="_blank"
                rel="noopener noreferrer"
              >
                Канал
              </a>
            )}
          </nav>
          <p>
            Поддержка {SERVICE.supportHours}. {SERVICE.supportPromise}
          </p>
        </div>
      </footer>
    </>
  );

  return (
    <html
      lang="ru"
      className={`${manrope.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        {authEnabled ? (
          <ClerkProvider
            publishableKey={clerkPublishableKey()}
            localization={ruRU}
            signInUrl="/sign-in"
            signUpUrl="/sign-up"
            signInFallbackRedirectUrl="/account"
            signUpFallbackRedirectUrl="/account"
            appearance={{
              variables: {
                colorPrimary: "var(--primary)",
                colorForeground: "var(--fg)",
                colorBackground: "var(--surface)",
                colorInput: "var(--surface-2)",
                colorInputForeground: "var(--fg)",
                borderRadius: "10px",
                fontFamily: "var(--font-sans)",
              },
            }}
          >
            {content}
          </ClerkProvider>
        ) : (
          content
        )}
      </body>
    </html>
  );
}
