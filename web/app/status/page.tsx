import type { Metadata } from "next";
import { getStatus, isStale, STATE_LABEL } from "@/lib/status";
import { SERVICE } from "@/lib/config";

export const metadata: Metadata = { title: "Статус узлов" };

// Страница пересобирается раз в минуту. Данные приходят от панели,
// свежесть проверяется отдельно — см. комментарий в lib/status.ts.
export const revalidate = 60;

// Состояние узла → тон плитки в сводке. Отдельной картой, а не подстановкой
// в класс: имена состояний приходят из панели, и подставлять их в CSS-класс
// напрямую значит однажды получить класс, которого нет в стилях.
const TILE_TONE = {
  up: "ok",
  degraded: "warn",
  down: "bad",
} as const;

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

export default async function Status() {
  const doc = await getStatus();

  return (
    <>
      <h1>Статус узлов</h1>

      <p className="lead">
        Что работает прямо сейчас. Обновляется автоматически, страницу можно
        просто перезагрузить.
      </p>

      {!doc && (
        <div className="notice">
          <p>
            <strong>Данные о состоянии сейчас недоступны.</strong>
          </p>
          <p className="small">
            Это значит, что не отвечает наша панель, а не обязательно то, что
            не работает VPN. Если у вас пропало соединение — напишите в
            поддержку, мы на связи {SERVICE.supportHours}.
          </p>
        </div>
      )}

      {doc && isStale(doc) && (
        <div className="notice">
          <p>
            <strong>Данные могли устареть.</strong> Последнее обновление:{" "}
            {formatTime(doc.generated_at)}.
          </p>
          <p className="small">
            Мы показываем это честно, вместо того чтобы выдавать старую
            проверку за свежую.
          </p>
        </div>
      )}

      {doc && (
        <>
          {/* Сводка перед таблицей. Человек, открывший страницу во время
              сбоя, должен получить ответ до того, как начнёт читать строки.
              Показываем только непустые состояния: тройка нулей рядом с
              «работает: 3» — это шум, а не информация. */}
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

          {/* Таблица уезжает в собственную прокрутку на узком экране,
              чтобы страница целиком не ехала вбок. */}
          <div className="table-scroll">
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Узел</th>
                  <th scope="col">Регион</th>
                  <th scope="col">Состояние</th>
                  <th scope="col">Проверен</th>
                </tr>
              </thead>
              <tbody>
                {doc.nodes.map((node) => (
                  <tr key={node.name}>
                    <td>{node.name}</td>
                    <td>{node.region}</td>
                    <td>
                      {/* Кружок дублируется словом: по одному цвету
                          состояние не прочитает дальтоник. */}
                      <span className={`state state-${node.state}`}>
                        <span className="dot" aria-hidden="true" />
                        {STATE_LABEL[node.state]}
                      </span>
                    </td>
                    <td>{formatTime(node.checked_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="small muted">
            Обновлено <span className="mono">{formatTime(doc.generated_at)}</span>{" "}
            по московскому времени. Проверка идёт каждые пять минут.
          </p>
        </>
      )}

      <h2>Почему здесь нет адресов</h2>

      <p>
        Мы показываем только название узла и страну. Адреса серверов на
        публичной странице — это готовый список для того, кто их блокирует,
        поэтому их здесь не будет и не должно быть ни у одного сервиса,
        который думает о своих пользователях.
      </p>

      <h2>Если узел перестал работать</h2>

      <p>
        Мы напишем об этом{" "}
        <a href={SERVICE.channel} target="_blank" rel="noopener noreferrer">
          в канале
        </a>{" "}
        в тот же час: что именно легло, с какого времени и когда рассчитываем
        починить. Ключи переезжают на рабочий узел автоматически,
        переустанавливать ничего не нужно.
      </p>

      <p className="small muted">
        Подписаться стоит даже если сейчас всё работает: когда узел ляжет,
        канал — единственное место, где вы узнаете об этом от нас, а не из
        собственных попыток открыть сайт.
      </p>
    </>
  );
}
