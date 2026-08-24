// Данные для страницы статуса.
//
// ВАЖНО про источник. Соблазн — проверять ноды прямо отсюда, из Next.js.
// Так делать нельзя: сайт живёт на Vercel, то есть за границей, и его проверка
// отвечает на вопрос «доступна ли нода из дата-центра в Европе». Пользователя
// же волнует «доступна ли она с МТС в Казани», а это совершенно другой ответ:
// блокировки живут у операторов, и снаружи их не видно.
//
// Поэтому проверяет панель (infra/panel/status-json.sh), она же складывает
// результат в status.json, а сайт его только показывает.

export type NodeState = "up" | "degraded" | "down";

export type NodeStatus = {
  name: string;        // Псевдоним. Никаких IP и хостнеймов наружу.
  region: string;
  state: NodeState;
  checked_at: string;  // ISO 8601
  latency_ms?: number | null; // Отклик панели до узла, не задержка пользователя.
};

export type StatusDoc = {
  generated_at: string;
  nodes: NodeStatus[];
};

export const STATE_LABEL: Record<NodeState, string> = {
  up: "Работает",
  degraded: "С перебоями",
  down: "Не работает",
};

// Считаем данные протухшими, если панель не обновляла их дольше 15 минут.
// Молчащая страница статуса хуже отсутствующей: она врёт уверенным голосом.
const STALE_AFTER_MS = 15 * 60 * 1000;

export function isStale(doc: StatusDoc, now = Date.now()): boolean {
  const generated = Date.parse(doc.generated_at);
  if (Number.isNaN(generated)) return true;
  return now - generated > STALE_AFTER_MS;
}

export async function getStatus(
  { fresh = false }: { fresh?: boolean } = {},
): Promise<StatusDoc | null> {
  // Переменная окружения остаётся главным источником: на другом окружении
  // можно направить сайт на иной приватный статус-источник. Публичный
  // endpoint панели — безопасный запасной вариант, чтобы отсутствие одной
  // переменной не превращало рабочую страницу статуса в пустую.
  const url = process.env.STATUS_URL || "https://sub.basaltworks.ru/status/status.json";

  try {
    // fresh — для /api/status, который опрашивает браузер: там кэш не нужен,
    // иначе «в прямом времени» превратится в «раз в минуту, если повезёт».
    // Первая отрисовка страницы, наоборот, кэшируется: сотня одновременно
    // открытых вкладок не должна сотней запросов лечь на панель.
    const res = await fetch(url, {
      ...(fresh ? { cache: "no-store" as const } : { next: { revalidate: 60 } }),
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    return (await res.json()) as StatusDoc;
  } catch {
    // Панель недоступна. Это само по себе новость, но врать «всё хорошо»
    // мы не будем — страница покажет, что данных нет.
    return null;
  }
}
