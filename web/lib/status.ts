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

export async function getStatus(): Promise<StatusDoc | null> {
  const url = process.env.STATUS_URL;

  if (!url) {
    // В разработке показываем пример, чтобы страницу было видно без панели.
    // В продакшене — честное «данных нет»: выдуманный статус на странице
    // статуса хуже, чем её отсутствие.
    if (process.env.NODE_ENV !== "production") {
      const sample = await import("@/data/status.sample.json");
      return sample.default as StatusDoc;
    }
    return null;
  }

  try {
    const res = await fetch(url, {
      next: { revalidate: 60 },
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
