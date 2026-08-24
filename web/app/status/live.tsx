"use client";

// Живая таблица статуса.
//
// Первый снимок приходит с сервера (initial) — страница читается и без
// JavaScript, и без ожидания первого запроса. Дальше её обновляет браузер
// сам, потому что человек открывает эту страницу ровно тогда, когда у него
// что-то не работает, и просить его жать F5, чтобы узнать, починили ли, —
// это ровно та пассивность, от которой мы уходим.

import { useCallback, useEffect, useRef, useState } from "react";
import { isStale, STATE_LABEL, type NodeState, type StatusDoc } from "@/lib/status";

// Панель пересчитывает status.json раз в пять минут, так что чаще, чем
// раз в полминуты, спрашивать нечего: увидим тот же файл.
const POLL_MS = 30_000;

// Состояние узла → тон плитки. Отдельной картой, а не подстановкой в класс:
// имена состояний приходят из панели, и подставлять их в CSS-класс напрямую
// значит однажды получить класс, которого нет в стилях.
const TILE_TONE: Record<NodeState, string> = {
  up: "ok",
  degraded: "warn",
  down: "bad",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Moscow",
  }).format(d);
}

function fastestNode(doc: StatusDoc) {
  return doc.nodes
    .filter((node) => node.state === "up" && typeof node.latency_ms === "number")
    .sort((a, b) => (a.latency_ms ?? Infinity) - (b.latency_ms ?? Infinity))[0];
}

export function LiveStatus({
  initial,
  supportHours,
}: {
  initial: StatusDoc | null;
  supportHours: string;
}) {
  const [doc, setDoc] = useState(initial);
  // Отдельно от doc: панель могла ответить пять минут назад и замолчать —
  // это разные новости, и вторая не должна стирать первую с экрана.
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [failing, setFailing] = useState(false);

  // Ссылка на актуальный запрос: вкладка, которую свернули и развернули
  // несколько раз, не должна накопить очередь ответов, приходящих вразнобой.
  const inflight = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;

    try {
      const res = await fetch("/api/status", {
        cache: "no-store",
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(String(res.status));

      const next = (await res.json()) as StatusDoc | null;
      setCheckedAt(Date.now());
      setFailing(next === null);
      // null не затирает таблицу: показать пустой экран вместо последних
      // известных данных — это потерять информацию, а не уточнить её.
      if (next !== null) setDoc(next);
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      setFailing(true);
    }
  }, []);

  useEffect(() => {
    // Свёрнутая вкладка не опрашивается: браузер и так душит таймеры в
    // фоне, а нам ни к чему держать открытой сотню спящих вкладок,
    // каждая из которых будит панель.
    const tick = () => {
      if (document.visibilityState === "visible") void refresh();
    };

    const id = window.setInterval(tick, POLL_MS);
    // При возврате на вкладку обновляем сразу, не дожидаясь такта: именно
    // в этот момент человек и смотрит на экран.
    document.addEventListener("visibilitychange", tick);

    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
      inflight.current?.abort();
    };
  }, [refresh]);

  if (!doc) {
    return (
      <div className="notice">
        <p>
          <strong>Данные о состоянии сейчас недоступны.</strong>
        </p>
        <p className="small">
          Это значит, что не отвечает наша панель, а не обязательно то, что не
          работает VPN. Если у вас пропало соединение — напишите в поддержку,
          мы на связи {supportHours}.
        </p>
      </div>
    );
  }

  const stale = isStale(doc);
  const fastest = fastestNode(doc);

  return (
    <>
      {failing && (
        <div className="notice">
          <p>
            <strong>Последнее обновление не получилось.</strong> Ниже — то, что
            мы знали на момент {formatTime(doc.generated_at)}.
          </p>
        </div>
      )}

      {stale && (
        <div className="notice">
          <p>
            <strong>Данные могли устареть.</strong> Последнее обновление:{" "}
            {formatTime(doc.generated_at)}.
          </p>
          <p className="small">
            Мы показываем это честно, вместо того чтобы выдавать старую проверку
            за свежую.
          </p>
        </div>
      )}

      {/* Сводка перед таблицей. Человек, открывший страницу во время сбоя,
          должен получить ответ до того, как начнёт читать строки. Показываем
          только непустые состояния: тройка нулей рядом с «работает: 3» — это
          шум, а не информация. */}
      <ul className="status-summary">
        <li className="tile">
          <span className="num">{doc.nodes.length}</span>
          <span className="label">узлов всего</span>
        </li>
        {(["up", "degraded", "down"] as const)
          .map((state) => ({
            state,
            count: doc.nodes.filter((n) => n.state === state).length,
          }))
          .filter(({ count }) => count > 0)
          .map(({ state, count }) => (
            <li key={state} className={`tile tile--${TILE_TONE[state]}`}>
              <span className="num">{count}</span>
              <span className="label">{STATE_LABEL[state].toLowerCase()}</span>
            </li>
          ))}
      </ul>

      {fastest && (
        <div className="notice">
          <p>
            <strong>⚡ Рекомендуем сейчас: {fastest.region}.</strong>{" "}
            Отклик от панели — около {fastest.latency_ms} мс.
          </p>
          <p className="small">
            Это технический отклик до узла, а не обещание скорости на вашем
            телефоне: мобильный оператор и регион влияют на результат.
          </p>
        </div>
      )}

      {/* Таблица уезжает в собственную прокрутку на узком экране, чтобы
          страница целиком не ехала вбок. aria-live — чтобы человек со
          скринридером узнал об изменении, а не остался с прочитанным
          вслух старым состоянием. */}
      <div className="table-scroll" aria-live="polite">
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Узел</th>
              <th scope="col">Регион</th>
              <th scope="col">Состояние</th>
              <th scope="col">Отклик</th>
              <th scope="col">Проверен</th>
            </tr>
          </thead>
          <tbody>
            {doc.nodes.map((node) => (
              <tr key={node.name}>
                <td>{node.name}</td>
                <td>{node.region}</td>
                <td>
                  {/* Кружок дублируется словом: по одному цвету состояние
                      не прочитает дальтоник. */}
                  <span className={`state state-${node.state}`}>
                    <span className="dot" aria-hidden="true" />
                    {STATE_LABEL[node.state]}
                  </span>
                </td>
                <td>{typeof node.latency_ms === "number" ? `${node.latency_ms} мс` : "—"}</td>
                <td>{formatTime(node.checked_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="small muted">
        Проверено панелью{" "}
        <span className="mono">{formatTime(doc.generated_at)}</span> по
        московскому времени, проверка идёт каждые пять минут.
        {checkedAt !== null && " Страница обновляется сама, перезагружать не нужно."}
      </p>
    </>
  );
}
