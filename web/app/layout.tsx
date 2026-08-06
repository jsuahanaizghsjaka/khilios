import type { Metadata } from "next";
import Link from "next/link";
import { SERVICE } from "@/lib/config";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: SERVICE.name,
    template: `%s — ${SERVICE.name}`,
  },
  description:
    "VPN, который работает, когда не работает ничего. Статус узлов открыт, о сбоях пишем сами, деньги возвращаем без разговоров.",
  // Поисковики сюда не нужны: продвижение таких сервисов в РФ запрещено
  // с марта 2024, и SEO в плане нет намеренно. Люди приходят из бота и канала.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body>
        <header className="site-head">
          <div className="wrap">
            <Link href="/" className="brand">
              {SERVICE.name}
            </Link>
            <nav>
              <Link href="/tariffs">Тарифы</Link>
              <Link href="/install">Установка</Link>
              <Link href="/status">Статус</Link>
            </nav>
          </div>
        </header>

        <main className="wrap">{children}</main>

        <footer className="site-foot">
          <div className="wrap">
            <nav>
              <Link href="/legal/offer">Оферта</Link>
              <Link href="/legal/privacy">Конфиденциальность</Link>
              <Link href="/legal/refund">Возврат</Link>
            </nav>
            <p>Поддержка {SERVICE.supportHours}. {SERVICE.supportPromise}</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
