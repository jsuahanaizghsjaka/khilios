"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SERVICE } from "@/lib/config";
import { ThemeToggle } from "./theme-toggle";

const LINKS = [
  { href: "/tariffs", label: "Тарифы" },
  { href: "/install", label: "Как подключить" },
  { href: "/status", label: "Статус" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Основная навигация">
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            // Подсвечиваем текущий раздел. Без этого непонятно, где ты
            // находишься, а aria-current ещё и озвучивается скринридером.
            aria-current={active ? "page" : undefined}
          >
            {link.label}
          </Link>
        );
      })}

      {/* Канал внешней ссылкой, поэтому обычный <a>, а не Link: next/link
          здесь ничего не ускоряет, а увести за пределы сайта должен честно. */}
      {SERVICE.channel && (
        <a href={SERVICE.channel} target="_blank" rel="noopener noreferrer">
          Канал
        </a>
      )}

      <ThemeToggle />
    </nav>
  );
}
