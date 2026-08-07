// Иконки в стиле Lucide: обводка 1.5, размер 20, одна визуальная семья.
// Эмодзи вместо иконок не используем: они выглядят по-разному на разных
// системах, не красятся темой и не масштабируются вместе с текстом.
//
// Иконки декоративные — рядом всегда есть текст, поэтому aria-hidden
// и никаких подписей для скринридера: он прочитает текст, а не картинку.

type Props = { className?: string };

const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false,
};

export function IconActivity({ className }: Props) {
  return (
    <svg {...base} className={className}>
      <path d="M3 12h4l3 8 4-16 3 8h4" />
    </svg>
  );
}

export function IconMegaphone({ className }: Props) {
  return (
    <svg {...base} className={className}>
      <path d="m3 11 15-6v14L3 13z" />
      <path d="M3 11v2a2 2 0 0 0 2 2h2" />
      <path d="M7 15v4a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-3" />
      <path d="M21 10v4" />
    </svg>
  );
}

export function IconRefund({ className }: Props) {
  return (
    <svg {...base} className={className}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
    </svg>
  );
}

export function IconRoute({ className }: Props) {
  return (
    <svg {...base} className={className}>
      <circle cx="6" cy="19" r="2.5" />
      <circle cx="18" cy="5" r="2.5" />
      <path d="M15.5 5H9a3 3 0 0 0 0 6h6a3 3 0 0 1 0 6H8.5" />
    </svg>
  );
}

export function IconCard({ className }: Props) {
  return (
    <svg {...base} className={className}>
      <rect x="2" y="5" width="20" height="14" rx="2.5" />
      <path d="M2 10h20" />
      <path d="M6 15h4" />
    </svg>
  );
}
