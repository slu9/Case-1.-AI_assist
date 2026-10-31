"use client";

import { CampaignPanel, StateBadge } from "@/components/Campaign";
import { Mascot } from "@/components/Mascot";
import { type ChatItem, useApp } from "@/components/Providers";
import { CHANNEL_LABELS, type CampaignState, type CampaignView, type ConfirmAction, type Dictionaries, type Draft, type SessionState, api, formatPeriod, viewOfDraft } from "@/lib";
import { AlertTriangle, ArrowUp, Check, CircleX, Mic, PanelRight, Paperclip, Slash, Sparkles } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const BUTTONS: Record<string, string> = {
  apply_draft: "Создать кампанию",
  to_moderation: "Отправить на модерацию",
  activate_campaign: "Запустить показ",
  stop_campaign: "Остановить показ",
  delete_campaign: "Удалить кампанию",
};
const DANGEROUS = new Set(["stop_campaign", "delete_campaign", "delete_banner", "delete_content", "delete_creative"]);
const HEADINGS: Record<string, string> = {
  apply_draft: "Создать кампанию и сохранить следующие изменения?",
  create_tag: "Создать новый тег и привязать к кампании?",
  create_place: "Создать новое место показа и привязать к кампании?",
  to_moderation: "Отправить кампанию на модерацию?",
  activate_campaign: "Запустить показ кампании?",
  stop_campaign: "Остановить показ кампании?",
};

function plural(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} ${one}`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${count} ${few}`;
  return `${count} ${many}`;
}

function DraftSummary({ view, dictionaries }: { view: CampaignView; dictionaries: Dictionaries | null }) {
  const segmentName = (code: string) => dictionaries?.segments.find((s) => s.code === code)?.name ?? code;
  const places = view.places.map((id) => dictionaries?.places.find((p) => p.id === id)?.description).filter(Boolean);
  const tags = view.tags.map((id) => dictionaries?.tags.find((t) => t.id === id)?.name).filter(Boolean);
  const channels = [...new Set(view.creatives.map((c) => CHANNEL_LABELS[c.channelCode] ?? c.channelCode))];
  return (
    <>
      <dl>
        <dt>Кампания</dt><dd>{view.name}</dd>
        <dt>Даты</dt><dd>{formatPeriod(view)}</dd>
        <dt>Тематика</dt><dd>{dictionaries?.topics.find((t) => t.value === view.topic)?.label ?? view.topic}</dd>
        {view.tags.length > 0 && <><dt>Теги</dt><dd>{tags.join(", ")}</dd></>}
        <dt>Аудитория</dt>
        <dd>{view.audienceType === "ALL_USERS" ? "Все пользователи" : view.included.map(segmentName).join(" или ")}</dd>
        {view.excluded.length > 0 && <><dt>Кроме</dt><dd>{view.excluded.map(segmentName).join(", ")}</dd></>}
        <dt>Места</dt><dd>{places.join(", ")}</dd>
        <dt>Каналы</dt><dd>{channels.join(", ") || "Не выбраны"}</dd>
      </dl>
      <div className="confirm-steps">
        <span><Check size={15} aria-hidden /> Сохраню кампанию как черновик и не отправлю на модерацию</span>
        {view.included.length > 0 && <span><Check size={15} aria-hidden /> Настрою аудиторию</span>}
        <span><Check size={15} aria-hidden /> Добавлю {plural(view.banners.length, "баннер", "баннера", "баннеров")}, {plural(view.contents.length, "экран", "экрана", "экранов")} и {plural(view.creatives.length, "креатив", "креатива", "креативов")}</span>
      </div>
    </>
  );
}

function Simple({ action }: { action: ConfirmAction }) {
  const id = action.input.campaignId;
  return <p>{action.title}{id ? `, кампания № ${id}` : ""}.</p>;
}

function draftSession(draft: Draft): SessionState {
  return { draft } as SessionState; // для сводки нужен только снимок черновика
}

/** Новая запись справочника подтверждается формой: менеджер проверяет заполненные поля (task.md §10.4). */
const FORMS: Record<string, [key: string, label: string][]> = {
  create_tag: [["name", "Название тега"]],
  create_place: [["description", "Название места"], ["code", "Код места"]],
};

function Confirm({ item }: { item: Extract<ChatItem, { kind: "confirm" }> }) {
  const { decide, busy, dictionaries } = useApp();
  const form = FORMS[item.actions[0]?.tool];
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries((form ?? []).map(([key]) => [key, String(item.actions[0].input[key] ?? "")])),
  );

  if (item.resolved) {
    const approved = item.resolved === "approved";
    return (
      <div className="confirm resolved">
        {approved ? <Check size={16} aria-hidden /> : <CircleX size={16} aria-hidden />}
        {approved ? "Подтверждено" : "Не подтверждено, изменений нет"}
      </div>
    );
  }

  const main = item.actions[0];
  const existing = main.tool === "apply_draft" && Boolean((main.input as unknown as Draft).campaignId);
  const heading = existing ? "Сохранить изменения кампании?" : HEADINGS[main.tool] ?? "Подтвердите действие";
  const warnings = item.review?.warnings ?? [];
  return (
    <section className="confirm rise" aria-label="Подтверждение действия">
      <h3>{heading}</h3>
      {main.tool === "apply_draft"
        ? <DraftSummary view={viewOfDraft(draftSession(main.input as unknown as Draft))} dictionaries={dictionaries} />
        : form
          ? form.map(([key, label]) => (
            <label key={key} className="field-block">
              <span className="small muted">{label}</span>
              <input className="field-input" value={values[key]} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
            </label>
          ))
          : item.actions.map((action, index) => <Simple key={index} action={action} />)}
      {main.tool === "apply_draft" && warnings.map((text) => (
        <div key={text} className="note amber"><AlertTriangle size={17} aria-hidden /><span>{text}</span></div>
      ))}
      <p className="small muted">Изменения сохранятся только после вашего подтверждения.</p>
      <div className="actions">
        <button className={`btn ${DANGEROUS.has(main.tool) ? "danger" : "primary"}`} disabled={!!busy || (form && form.some(([key]) => !values[key].trim()))} onClick={() => decide(item, true, form ? values : undefined)}>
          {existing ? "Сохранить" : BUTTONS[main.tool] ?? "Подтвердить"}
        </button>
        <button className="btn secondary" disabled={!!busy} onClick={() => decide(item, false)}>Вернуться и изменить</button>
      </div>
    </section>
  );
}

export function ChatItemView({ item }: { item: ChatItem }) {
  if (item.kind === "user") return <div className="msg-user rise">{item.text}</div>;
  if (item.kind === "error") {
    return <div className="error-card rise" role="alert"><CircleX size={18} aria-hidden style={{ flex: "none" }} />{item.text}</div>;
  }
  if (item.kind === "confirm") return <Confirm item={item} />;
  if (item.kind === "success") {
    return (
      <section className="success rise">
        <span className="success-mark"><Check size={24} aria-hidden /></span>
        <h3>Кампания отправлена на модерацию</h3>
        <p>Теперь очередь модератора: он одобрит кампанию или вернёт её с комментарием. После одобрения запуск останется за вами.</p>
        {item.campaignId && <div className="actions"><Link className="btn primary" href={`/campaigns/${item.campaignId}`}>Перейти к кампании</Link></div>}
      </section>
    );
  }
  return (
    <div className="msg-ai rise">
      <span className="ai-mark"><Sparkles size={16} aria-hidden /></span>
      <div className="ai-body"><ReactMarkdown>{item.text}</ReactMarkdown></div>
    </div>
  );
}

const COMMANDS = [
  { label: "Показать сводку кампании", text: "Покажи сводку кампании" },
  { label: "Проверить кампанию", text: "Проверь кампанию и объясни предупреждения" },
  { label: "Отправить на модерацию", text: "Отправляй на модерацию" },
  { label: "Показать историю", text: "Покажи историю кампании" },
];

type Recognition = { lang: string; interimResults: boolean; start(): void; stop(): void; onresult: (e: { results: { 0: { transcript: string } }[] }) => void; onend: () => void };

function recognition(): Recognition | null {
  const source = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  const Engine = source.SpeechRecognition ?? source.webkitSpeechRecognition;
  return Engine ? new Engine() : null;
}

export function Composer({ suggestions = [], placeholder, large }: { suggestions?: string[]; placeholder: string; large?: boolean }) {
  const { send, busy, draftText, setDraftText, toast } = useApp();
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [listening, setListening] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const engine = useRef<Recognition | null>(null);

  useEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [draftText]);

  useEffect(() => {
    if (draftText) area.current?.focus();
  }, [draftText]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (event.key === "/" && !["TEXTAREA", "INPUT", "SELECT"].includes(target.tagName)) {
        event.preventDefault();
        area.current?.focus();
        setCommandsOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (text = draftText) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setDraftText("");
    setCommandsOpen(false);
    void send(trimmed);
  };

  const toggleVoice = () => {
    if (listening) {
      engine.current?.stop();
      return;
    }
    const instance = recognition();
    if (!instance) {
      toast("Голосовой ввод не поддерживается в этом браузере");
      return;
    }
    instance.lang = "ru-RU";
    instance.interimResults = false;
    instance.onresult = (event) => setDraftText(`${draftText} ${event.results[0][0].transcript}`.trim());
    instance.onend = () => setListening(false);
    engine.current = instance;
    instance.start();
    setListening(true);
  };

  return (
    <div className={large ? "" : "composer-wrap"}>
      {suggestions.length > 0 && (
        <div className="suggestions">
          {suggestions.map((text) => (
            <button key={text} className="chip-button" disabled={!!busy} onClick={() => submit(text)}>{text}</button>
          ))}
        </div>
      )}
      <div className="composer">
        {commandsOpen && (
          <div className="commands" role="menu" aria-label="Быстрые команды">
            {COMMANDS.map((command) => (
              <button key={command.label} role="menuitem" onClick={() => submit(command.text)}>{command.label}</button>
            ))}
          </div>
        )}
        <textarea
          ref={area}
          rows={large ? 3 : 1}
          value={draftText}
          placeholder={placeholder}
          aria-label="Сообщение ассистенту"
          onChange={(e) => {
            setDraftText(e.target.value);
            setCommandsOpen(e.target.value === "/");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
            if (e.key === "Escape") setCommandsOpen(false);
          }}
        />
        <div className="composer-row">
          <button className="icon-btn" aria-label="Быстрые команды" title="Быстрые команды ( / )" onClick={() => setCommandsOpen(!commandsOpen)}>
            <Slash size={18} />
          </button>
          <button className="icon-btn" disabled aria-label="Прикрепить изображение" title="Появится вместе с генерацией изображений">
            <Paperclip size={18} />
          </button>
          <button className={`icon-btn ${listening ? "on" : ""}`} aria-pressed={listening} aria-label="Голосовой ввод" title="Голосовой ввод" onClick={toggleVoice}>
            <Mic size={18} />
          </button>
          <button className="send" disabled={!draftText.trim() || !!busy} aria-label="Отправить" onClick={() => submit()}>
            <ArrowUp size={19} />
          </button>
        </div>
      </div>
    </div>
  );
}

const QUICK = [
  { label: "Продуктовая кампания", text: "Хочу запустить продуктовую кампанию. Подскажи, какие данные нужны." },
  { label: "Сезонная акция", text: "Хочу создать сезонную акцию. Подскажи, какие данные нужны." },
  { label: "Изменить кампанию", text: "Покажи кампании, которые можно изменить." },
  { label: "Замечания модератора", text: "Покажи кампании с замечаниями модератора и предложи исправления." },
];

const EXAMPLES = [
  "Запусти с 5 ноября рекламу новой кофейни для жителей Москвы. Покажи сторис на iOS и Android",
  "Кампания онлайн-курса для молодых родителей, смарт-баннер на главном, до конца года",
];

function Welcome() {
  const { send, busy } = useApp();
  return (
    <section className="home-stage">
      <div className="home-mascot"><Mascot mood={busy ? "thinking" : "idle"} variant="hero" /></div>
      <h2 className="home-title rise">Какую кампанию <span>создадим?</span></h2>
      <div className="home-box rise">
        <Composer large placeholder="Опишите кампанию своими словами, остальное соберу я" />
        <div className="stickers" aria-label="Быстрые сценарии">
          {QUICK.map(({ label, text }) => (
            <button key={label} className="sticker" disabled={!!busy} onClick={() => send(text)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="home-examples rise" aria-label="Примеры брифов">
        {EXAMPLES.map((text) => <button key={text} disabled={!!busy} onClick={() => send(text)}>{text}</button>)}
      </div>
    </section>
  );
}

function suggestionsFor(session: ReturnType<typeof useApp>["active"]): string[] {
  const state = session?.session;
  if (!state || state.awaitingConfirmation) return [];
  if (state.draft.finished) return ["Отправляй на модерацию", "Покажи предупреждения"];
  if (state.progress.percent === 100) return ["Покажи сводку", "Создавай кампанию"];
  return [];
}

export function Workspace() {
  const { active, send, busy, actor } = useApp();
  const [panelOpen, setPanelOpen] = useState(false);
  const feed = useRef<HTMLDivElement>(null);
  const params = useSearchParams();
  const campaignParam = params.get("campaign");
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (campaignParam && started.current !== campaignParam) {
      started.current = campaignParam;
      void send(`Открой кампанию № ${campaignParam} и расскажи, что с ней нужно сделать.`, Number(campaignParam));
    }
  }, [campaignParam, send]);

  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [active?.items.length, busy]);

  const [state, setState] = useState<CampaignState>("DRAFT");
  const campaignId = active?.campaignId;
  useEffect(() => {
    setState("DRAFT");
    if (campaignId) api.campaign(campaignId, actor).then((c) => setState(c.state)).catch(() => undefined);
  }, [campaignId, actor, active?.revision]);

  const showWelcome = !active || active.items.length === 0;

  if (showWelcome) return <div className="workspace home"><Welcome /></div>;

  return (
    <div className="workspace">
      <div className="chat">
        <div className="chat-top">
          <h1>{(active.session?.draft.campaign.name as string) ?? active.title}</h1>
          <StateBadge state={state} />
          <span className="saved">
            <Check size={15} aria-hidden />
            <span>{campaignId ? "Сохранено" : "Черновик в диалоге"}</span>
          </span>
          <button className="icon-btn panel-toggle" onClick={() => setPanelOpen(true)} aria-label="Открыть кампанию">
            <PanelRight size={19} />
          </button>
        </div>
        <div className="feed" ref={feed} aria-live="polite">
          {active.items.map((item) => <ChatItemView key={item.id} item={item} />)}
          {busy && <div className="status rise"><i aria-hidden />{busy}</div>}
        </div>
        <Composer suggestions={suggestionsFor(active)} placeholder="Напишите ответ или новое пожелание…" />
      </div>
      <div className={`scrim ${panelOpen ? "open" : ""}`} onClick={() => setPanelOpen(false)} aria-hidden />
      <CampaignPanel open={panelOpen} onClose={() => setPanelOpen(false)} />
    </div>
  );
}
