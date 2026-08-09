import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { SERVICE } from "@/lib/config";
import { Nav } from "./nav";
import "./globals.css";

// Шрифты скачиваются на сборке и раздаются с нашего домена.
// Для сервиса, который продаёт приватность, тянуть шрифт с чужого CDN
// на каждой загрузке — это отдавать своих пользователей мимо своей же
// политики конфиденциальности.
const inter = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-sans",
});

// Моноширинный — для данных: имена узлов, время проверки, цены.
// Цифры в нём не «пляшут» между строками таблицы.
const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-mono",
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

// Тема применяется до первой отрисовки, иначе страница моргает тёмным
// у тех, кто выбрал светлую. Скрипт намеренно крошечный и синхронный:
// всё, что он делает, — переносит сохранённый выбор на <html>.
const themeScript = `try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru" className={`${inter.variable} ${mono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
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
      </body>
    </html>
  );
}
