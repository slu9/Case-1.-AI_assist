export type Role = "campaignManager" | "campaignModerator";

export type CampaignState =
  | "DRAFT" | "ON_MODERATION" | "NEEDS_WORK" | "APPROVED" | "ACTIVE" | "ACTIVE_EDITING" | "STOPPED" | "ARCHIVED";

export type Topic = { value: string; label: string };
export type Tag = { id: number; name: string };
export type Place = { id: number; code: string; description: string; defaultBanner: string | null; state: string };
export type Segment = { code: string; name: string; type: string; state: string; count: number };
export type BannerType = {
  id: number; code: string; description: string; titleMaxLength: number; textMaxLength: number; channels: string[];
};
export type Dictionaries = { topics: Topic[]; tags: Tag[]; places: Place[]; segments: Segment[]; bannerTypes: BannerType[] };

export type TextStyle = { fontSize?: number; fontWeight?: string; textColor?: string };
export type BannerContent = {
  title?: string; text?: string; titleStyle?: TextStyle; textStyle?: TextStyle;
  background?: { color: string }; image?: { url: string }; buttonName?: string;
  actionType: string; link?: { iOS?: string; android?: string; web?: string }; voiceOver?: string;
};
export type PromoComponent =
  | { role: "text"; format: "none" | "html"; text: string; textStyle?: TextStyle }
  | { role: "image"; url: string; aspectRatio?: number }
  | { role: "button"; text: string; actionType: string; textStyle?: TextStyle; style?: { backgroundColor?: string } };
export type PromoContent = {
  role: "promo";
  component: { role: "linearContainer"; style?: { backgroundColor?: string }; components: PromoComponent[] };
};

export type CampaignListItem = {
  id: number; name: string; state: CampaignState; published: boolean; topic: string;
  startDate: string; startTime: string; endDate: string | null; endTime: string | null;
};
export type CampaignDetails = CampaignListItem & {
  marketingName: string | null; tags: number[]; keywords: string | null; audienceType: string;
  weight: number; initialCtr: number; author: string; lastEditAuthor: string; places: number[];
  banners: { id: number; name: string; bannerTypeId: number; content: BannerContent }[];
  contents: { id: number; name: string; contentType: string; content: PromoContent }[];
  creatives: { id: number; name: string; bannerId: number; contentId: number | null; channelCode: string }[];
  segments: { included: string[]; excluded: string[] };
};
export type AuditEntry = {
  entity: string; entityId: number; action: string; changes: Record<string, { from: unknown; to: unknown }> | null;
  at: string; actor: string; comment: string | null;
};
export type ValidationIssue = { code: string; message: string; field: string | null };
export type Warnings = { errors: ValidationIssue[]; warnings: string[] };

/** Единый вид кампании для панели: черновик из диалога и сохранённая запись. */
export type CampaignView = {
  id: number | null; name?: string; marketingName?: string | null; topic?: string; tags: number[];
  startDate?: string; startTime?: string; endDate?: string | null; endTime?: string | null; hasEnd: boolean;
  audienceType?: string; weight?: number; initialCtr?: number; places: number[];
  included: string[]; excluded: string[]; state: CampaignState; published: boolean;
  banners: { ref: string; name: string; bannerTypeId: number; content: BannerContent }[];
  contents: { ref: string; name: string; content: PromoContent }[];
  creatives: { name: string; bannerRef: string; contentRef: string | null; channelCode: string }[];
};

export type Draft = {
  weightReasons?: string[];
  campaign: Record<string, unknown>;
  segments: { included: string[]; excluded: string[] };
  banners: Record<string, { name: string; bannerTypeId: number; content: BannerContent }>;
  contents: Record<string, { name: string; content: PromoContent }>;
  creatives: { name: string; bannerKey: string; contentKey: string | null; channelCode: string }[];
  campaignId: number | null;
  finished: boolean;
};
export type Advisory = { code: string; message: string };
export type Review = {
  ready: boolean; errors: ValidationIssue[]; warnings: string[]; advisories: Advisory[];
  audience: { semantics: string };
};
export type SessionState = {
  id: string; user: string; role: Role; draft: Draft; review: Review;
  progress: { percent: number; missing: string[]; ready: boolean };
  awaitingConfirmation: boolean;
};
export type ConfirmAction = { tool: string; title: string; input: Record<string, unknown> };
export type Turn = { text: string; confirmation: ConfirmAction[] | null; error: string | null };

export const STATE_LABELS: Record<CampaignState, string> = {
  DRAFT: "Черновик",
  ON_MODERATION: "На модерации",
  NEEDS_WORK: "Требует доработки",
  APPROVED: "Одобрена",
  ACTIVE: "Активна",
  ACTIVE_EDITING: "Активна, есть правки",
  STOPPED: "Остановлена",
  ARCHIVED: "В архиве",
};

export const STATE_TONES: Record<CampaignState, string> = {
  DRAFT: "neutral",
  ON_MODERATION: "amber",
  NEEDS_WORK: "red",
  APPROVED: "lime",
  ACTIVE: "green",
  ACTIVE_EDITING: "green",
  STOPPED: "neutral",
  ARCHIVED: "neutral",
};

export const AUDIT_ACTIONS: Record<string, string> = {
  CREATE: "создание",
  UPDATE: "изменение",
  DELETE: "удаление",
  TO_MODERATION: "отправка на модерацию",
  DECLINE: "возврат на доработку",
  APPROVE: "одобрение",
  ACTIVATE: "запуск показа",
  STOP: "остановка показа",
};

export const AUDIT_ENTITIES: Record<string, string> = {
  CAMPAIGN: "Кампания",
  BANNER: "Баннер",
  CONTENT: "Промо-экран",
  CREATIVE: "Креатив",
  SEGMENTS: "Сегменты",
};

export const PEOPLE: Record<string, string> = { "ivanov.p": "Павел Иванов", "petrova.m": "Мария Петрова" };

export const CHANNELS = ["iOS", "ANDROID", "WEB"] as const;
export const CHANNEL_LABELS: Record<string, string> = { iOS: "iOS", ANDROID: "Android", WEB: "Web" };

export function formatDate(date?: string | null): string {
  if (!date) return "";
  return new Date(`${date}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export function formatPeriod(c: { startDate?: string | null; endDate?: string | null }): string {
  if (!c.startDate) return "Не указаны";
  return c.endDate ? `${formatDate(c.startDate)} — ${formatDate(c.endDate)}` : `с ${formatDate(c.startDate)}, бессрочно`;
}

export function formatCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`;
  if (count >= 1_000) return `${Math.round(count / 1_000)} тыс.`;
  return String(count);
}

export function viewOfDetails(c: CampaignDetails): CampaignView {
  return {
    ...c,
    hasEnd: true,
    included: c.segments.included,
    excluded: c.segments.excluded,
    banners: c.banners.map((b) => ({ ...b, ref: String(b.id) })),
    contents: c.contents.map((x) => ({ ...x, ref: String(x.id) })),
    creatives: c.creatives.map((x) => ({
      name: x.name,
      bannerRef: String(x.bannerId),
      contentRef: x.contentId === null ? null : String(x.contentId),
      channelCode: x.channelCode,
    })),
  };
}

export function viewOfDraft(session: SessionState): CampaignView {
  const { draft } = session;
  const c = draft.campaign as Partial<CampaignView>;
  return {
    id: draft.campaignId,
    name: c.name,
    marketingName: c.marketingName,
    topic: c.topic,
    tags: c.tags ?? [],
    startDate: c.startDate,
    startTime: c.startTime,
    endDate: c.endDate,
    endTime: c.endTime,
    hasEnd: "endDate" in draft.campaign,
    audienceType: c.audienceType,
    weight: c.weight,
    initialCtr: c.initialCtr,
    places: c.places ?? [],
    included: draft.segments.included,
    excluded: draft.segments.excluded,
    state: "DRAFT",
    published: false,
    banners: Object.entries(draft.banners).map(([ref, b]) => ({ ref, ...b })),
    contents: Object.entries(draft.contents).map(([ref, x]) => ({ ref, ...x })),
    creatives: draft.creatives.map((x) => ({
      name: x.name, bannerRef: x.bannerKey, contentRef: x.contentKey, channelCode: x.channelCode,
    })),
  };
}

/** Относительная яркость и контраст по WCAG; прозрачность цвета не учитывается. */
function luminance(hex: string): number {
  const channel = (start: number) => {
    const value = parseInt(hex.slice(start, start + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

export type Actor = { user: string; role: Role };

export class ApiFailure extends Error {}

async function backend<T>(path: string, actor: Actor, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/backend${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-User": actor.user, "X-Role": actor.role },
    });
  } catch {
    throw new ApiFailure("Сервис кампаний недоступен. Проверьте, что он запущен.");
  }
  if (response.status >= 500) throw new ApiFailure("Сервис кампаний недоступен. Проверьте, что он запущен.");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const messages = (body?.errors ?? []).map((e: { message: string }) => e.message);
    throw new ApiFailure(messages.join(". ") || "Не удалось выполнить действие");
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const api = {
  async dictionaries(actor: Actor): Promise<Dictionaries> {
    const [topics, tags, places, segments, bannerTypes] = await Promise.all([
      backend<Dictionaries["topics"]>("/topics", actor),
      backend<Dictionaries["tags"]>("/tags", actor),
      backend<Dictionaries["places"]>("/places", actor),
      backend<Dictionaries["segments"]>("/segments", actor),
      backend<Dictionaries["bannerTypes"]>("/banner-types", actor),
    ]);
    return { topics, tags, places, segments, bannerTypes };
  },
  campaigns: (actor: Actor) => backend<CampaignListItem[]>("/campaigns", actor),
  campaign: (id: number, actor: Actor) => backend<CampaignDetails>(`/campaigns/${id}`, actor),
  warnings: (id: number, actor: Actor) => backend<Warnings>(`/campaigns/${id}/warnings`, actor),
  audit: (id: number, actor: Actor) => backend<AuditEntry[]>(`/campaigns/${id}/audit`, actor),
  action: (id: number, name: string, actor: Actor, body?: object) =>
    backend(`/campaigns/${id}/${name}`, actor, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  remove: (id: number, actor: Actor) => backend(`/campaigns/${id}`, actor, { method: "DELETE" }),
};

export type StreamEvent =
  | { type: "status"; label: string }
  | { type: "turn"; turn: Turn; session?: SessionState };

async function readStream(response: Response, onEvent: (event: StreamEvent) => void) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
  }
}

async function agentPost(path: string, body: object): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`/api/agent${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiFailure("Ассистент недоступен. Проверьте, что он запущен.");
  }
  if (response.status === 404) throw new ApiFailure("Этот диалог устарел: сервис перезапускался. Начните новую кампанию.");
  if (!response.ok) throw new ApiFailure("Ассистент недоступен. Проверьте, что он запущен.");
  return response;
}

export const agent = {
  async createSession(actor: Actor): Promise<SessionState> {
    return (await agentPost("/sessions", actor)).json();
  },
  async send(sessionId: string, text: string, onEvent: (event: StreamEvent) => void) {
    await readStream(await agentPost(`/sessions/${sessionId}/messages`, { text }), onEvent);
  },
  async decide(sessionId: string, approved: boolean, onEvent: (event: StreamEvent) => void, edits?: Record<string, string>) {
    await readStream(await agentPost(`/sessions/${sessionId}/decision`, { approved, edits }), onEvent);
  },
};
