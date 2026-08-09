"use client";

import { useEffect, useState } from "react";

// Переключатель темы. Тёмная — по умолчанию, светлая — выбором.
//
// Выбор хранится в localStorage и применяется скриптом в <head> ДО отрисовки
// (см. layout.tsx). Без этого страница успевает моргнуть тёмным, прежде чем
// React примонтируется — а моргание на каждой загрузке раздражает сильнее,
// чем отсутствие переключателя.

type Theme = "dark" | "light";

function currentTheme(): Theme {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  // Явного выбора нет — значит действует системная настройка.
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export function ThemeToggle() {
  // На сервере темы нет, поэтому до монтирования кнопка не знает, что рисовать.
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => setTheme(currentTheme()), []);

  function toggle() {
    const next: Theme = (theme ?? currentTheme()) === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Приватный режим или запрещённое хранилище: тема применится
      // на эту сессию и не сохранится. Ронять из-за этого нечего.
    }
    setTheme(next);
  }

  // До монтирования держим место кнопки, но не подписываем её: подпись
  // «включить светлую» на светлой теме — это хуже, чем пустая кнопка.
  const label =
    theme === null
      ? undefined
      : theme === "dark"
        ? "Включить светлую тему"
        : "Включить тёмную тему";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={label}
      title={label}
    >
      {theme === "light" ? <MoonIcon /> : <SunIcon />}
    </button>
  );
}

const base = {
  width: 17,
  height: 17,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false,
};

function SunIcon() {
  return (
    <svg {...base}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg {...base}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}
