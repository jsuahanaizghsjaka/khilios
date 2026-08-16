"use client";

import { useEffect, useState } from "react";
import type { Plan } from "@/lib/config";

const NODES = [
  { id: "se", label: "Швеция" },
  { id: "de", label: "Германия" },
  { id: "nl", label: "Нидерланды" },
  { id: "fi", label: "Финляндия" },
] as const;

const STORAGE_KEY = "khilios-preferred-node";
const NODE_EVENT = "khilios-node-change";

function isNode(value: string | null): value is (typeof NODES)[number]["id"] {
  return NODES.some((node) => node.id === value);
}

function usePreferredNode() {
  const [node, setNodeState] = useState<(typeof NODES)[number]["id"]>("de");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (isNode(saved)) setNodeState(saved);
    } catch {}

    const sync = (event: Event) => {
      const next = (event as CustomEvent<string>).detail;
      if (isNode(next)) setNodeState(next);
    };
    window.addEventListener(NODE_EVENT, sync);
    return () => window.removeEventListener(NODE_EVENT, sync);
  }, []);

  const setNode = (next: (typeof NODES)[number]["id"]) => {
    setNodeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {}
    window.dispatchEvent(new CustomEvent(NODE_EVENT, { detail: next }));
  };

  return [node, setNode] as const;
}

function telegramUrl(botUrl: string, start: string, node: string) {
  if (!botUrl) return "";
  try {
    const url = new URL(botUrl);
    url.searchParams.set("start", `${start}_${node}`.slice(0, 64));
    return url.toString();
  } catch {
    return botUrl;
  }
}

export function BotLink({
  botUrl,
  start,
  className,
  children,
}: {
  botUrl: string;
  start: string;
  className: string;
  children: React.ReactNode;
}) {
  const [node] = usePreferredNode();
  const href = telegramUrl(botUrl, start, node);

  if (!href) {
    return <span className={`${className} is-disabled`} aria-disabled="true">Скоро открытие</span>;
  }
  return <a className={className} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

function deviceWord(count: number) {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return "устройств";
  if (mod10 === 1) return "устройство";
  if (mod10 >= 2 && mod10 <= 4) return "устройства";
  return "устройств";
}

type LandingInteractiveProps =
  | { mode: "nodes" }
  | { mode: "plans"; botUrl: string; plans: Plan[] };

export function LandingInteractive(props: LandingInteractiveProps) {
  const [node, setNode] = usePreferredNode();
  const selected = NODES.find((item) => item.id === node)!;

  if (props.mode === "nodes") {
    return (
      <div className="node-picker">
        <span className="node-picker-label">Предпочитаемая точка выхода</span>
        <div className="node-picker-list" role="group" aria-label="Выбор точки выхода">
          {NODES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.id === node ? "active" : undefined}
              aria-pressed={item.id === node}
              onClick={() => setNode(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="node-picker-selected">
          Сохранено: <strong>{selected.label}</strong>
        </span>
        <p>
          Выбор хранится только в этом браузере и передаётся боту при запуске.
          Если точка недоступна, клиент сможет использовать другой рабочий узел.
        </p>
      </div>
    );
  }

  return (
    <div className="landing-plans">
      {props.plans.map((plan) => {
        const href = telegramUrl(props.botUrl, `plan_${plan.id}`, node);
        return (
          <article className={`landing-plan${plan.featured ? " featured" : ""}`} key={plan.id}>
            <div className="landing-plan-head">
              <span>{plan.name}</span>
              <span className="device-badge">{plan.devices} {deviceWord(plan.devices)}</span>
            </div>
            <div className="landing-price">
              {plan.price.toLocaleString("ru-RU")} ₽
              {plan.featured && <span className="popular-badge">Обычно берут этот</span>}
            </div>
            <div className="landing-period">{plan.period}</div>
            <ul>
              <li>Все доступные узлы</li>
              <li>{plan.devices} {deviceWord(plan.devices)}</li>
              <li>Без лимита трафика</li>
              <li>{plan.price === 0 ? "Без карты и автосписания" : "Возврат за оставшиеся дни"}</li>
            </ul>
            <div className="landing-plan-footer">
              {href ? (
                <a className={`pill ${plan.featured ? "pill-primary" : "pill-outline"}`} href={href} target="_blank" rel="noopener noreferrer">
                  Выбрать
                </a>
              ) : (
                <span className="pill pill-outline is-disabled" aria-disabled="true">Скоро открытие</span>
              )}
              <p>{plan.note}</p>
            </div>
          </article>
        );
      })}
    </div>
  );
}
