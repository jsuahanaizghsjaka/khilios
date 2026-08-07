import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import { SERVICE } from "@/lib/config";
import { Nav } from "./nav";
import "./globals.css";

// Шрифт скачивается на сборке и раздаётся с нашего домена.
// Для сервиса, который продаёт приватность, тянуть шрифт с чужого CDN
// на каждой загрузке — это отдавать своих пользователей мимо своей же
// политики конфиденциальности.
const inter = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: {
    default: SERVICE.name,
    template: `%s — ${SERVICE.name}`,
  },
  description:
    "Защищённое соединение, которое не надо настраивать. Статус узлов открыт, о сбоях пишем сами, деньги возвращаем без разговоров.",
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
    <html lang="ru" className={inter.variable}>
      <body>
        <header className="site-head">
          <div className="wrap">
            <Link href="/" className="brand">
              {SERVICE.name}
            </Link>
            <Nav />
          </div>
        </header>

        <main className="wrap">{children}</main>

        <footer className="site-foot">
          <div className="wrap">
            <nav aria-label="Правовая информация">
              <Link href="/legal/offer">Оферта</Link>
              <Link href="/legal/privacy">Конфиденциальность</Link>
              <Link href="/legal/refund">Возврат</Link>
            </nav>
            <p>
              Поддержка {SERVICE.supportHours}. {SERVICE.supportPromise}
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
