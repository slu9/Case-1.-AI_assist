"use client";

import { CreativePreview } from "@/components/CreativePreview";
import { Mascot } from "@/components/Mascot";
import { useApp } from "@/components/Providers";
import { AUDIT_ACTIONS, AUDIT_ENTITIES, ApiFailure, type AuditEntry, type CampaignDetails, type CampaignState, type CampaignView, type Dictionaries, PEOPLE, STATE_LABELS, STATE_TONES, type Warnings, api, formatCount, formatDate, formatPeriod, viewOfDetails, viewOfDraft } from "@/lib";
import { AlertTriangle, ArrowRightLeft, CheckCircle2, CircleX, Info, MessageSquareWarning, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

export function StateBadge({ state }: { state: CampaignState }) {
  return <span className={`badge ${STATE_TONES[state]}`}>{STATE_LABELS[state]}</span>;
}

const STEPS: { state: CampaignState; label: string }[] = [
  { state: "DRAFT", label: "Черновик" },
  { state: "ON_MODERATION", label: "Модерация" },
  { state: "APPROVED", label: "Одобрена" },
  { state: "ACTIVE", label: "Активна" },
  { state: "STOPPED", label: "Остановлена" },
];
const POSITION: Partial<Record<CampaignState, number>> = { NEEDS_WORK: 1, ACTIVE_EDITING: 3 };

export function Timeline({ state }: { state: CampaignState }) {
  const position = POSITION[state] ?? STEPS.findIndex((s) => s.state === state);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="timeline" role="img" aria-label={`Статус: ${STATE_LABELS[state]}`}>
        {STEPS.map((step, index) => (
          <div key={step.state} className={index < position ? "done" : index === position ? "now" : ""}>
            <i />
            <span>{step.label}</span>
          </div>
        ))}
      </div>
      {POSITION[state] !== undefined && <span className="small muted">Сейчас: {STATE_LABELS[state]}</span>}
    </div>
  );
}

export function AudienceBlock({ campaign, dictionaries, onReplace }: {
  campaign: CampaignView;
  dictionaries: Dictionaries;
  onReplace?: (name: string, excluded: boolean) => void;
}) {
  const segments = (codes: string[]) => codes.map((code) => dictionaries.segments.find((s) => s.code === code)).filter((s) => s !== undefined);
  const included = segments(campaign.included);
  const excluded = segments(campaign.excluded);
  const types = new Set(included.map((s) => s.type));

  if (campaign.audienceType === "ALL_USERS") {
    return <div className="note lime"><Info size={17} aria-hidden /><span>Кампанию увидят все пользователи приложения.</span></div>;
  }
  if (included.length === 0) {
    return <div className="empty-state"><b>Аудитория ещё не выбрана</b><span>Опишите её в брифе, и ассистент подберёт сегменты</span></div>;
  }

  return (
    <div className="stack">
      <div>
        <div className="section-title">Кто увидит</div>
        <div className="chips">
          {included.map((s) => (
            <span key={s.code} className="seg">
              {s.name} <b className="mono">{formatCount(s.count)}</b>
              {onReplace && (
                <button aria-label={`Заменить сегмент ${s.name}`} title="Заменить" onClick={() => onReplace(s.name, false)}>
                  <ArrowRightLeft size={13} aria-hidden />
                </button>
              )}
            </span>
          ))}
        </div>
      </div>

      {types.size > 1 && (
        <div className="note amber">
          <AlertTriangle size={17} aria-hidden />
          <span>
            Сегменты объединяются через «ИЛИ»: кампания охватит клиентов из {included.map((s) => `«${s.name}»`).join(" или ")},
            а не их пересечение.
          </span>
        </div>
      )}

      {excluded.length > 0 && (
        <div>
          <div className="section-title">Кто не увидит</div>
          <div className="chips">
            {excluded.map((s) => (
              <span key={s.code} className="seg excluded">
                {s.name.replace("Исключение. ", "")} <b className="mono">{formatCount(s.count)}</b>
                {onReplace && (
                  <button aria-label={`Убрать исключение ${s.name}`} title="Изменить" onClick={() => onReplace(s.name, true)}>
                    <X size={13} aria-hidden />
                  </button>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="small muted">Общий охват не показан: пересечения между сегментами неизвестны.</p>
    </div>
  );
}

export function PlacesBlock({ campaign, dictionaries }: { campaign: CampaignView; dictionaries: Dictionaries }) {
  const places = campaign.places.map((id) => dictionaries.places.find((p) => p.id === id)).filter((p) => p !== undefined);
  if (places.length === 0) {
    return <div className="empty-state"><b>Места показа не выбраны</b><span>Напишите, где показывать кампанию</span></div>;
  }
  const covered = new Set(
    campaign.creatives.flatMap((c) => {
      const banner = campaign.banners.find((b) => b.ref === c.bannerRef);
      const type = dictionaries.bannerTypes.find((t) => t.id === banner?.bannerTypeId);
      return type ? [type.code] : [];
    }),
  );

  return (
    <div className="stack" style={{ gap: 8 }}>
      {places.map((place) => {
        const isCovered = !place.defaultBanner || covered.has(place.defaultBanner);
        const type = dictionaries.bannerTypes.find((t) => t.code === place.defaultBanner);
        return (
          <div key={place.id} className="place">
            <div className="place-row">
              <b style={{ fontWeight: 600 }}>{place.description}</b>
              <span className={`badge ${place.state === "ACTIVE" ? "green" : "amber"}`}>
                {place.state === "ACTIVE" ? "Активно" : "Неактивно"}
              </span>
            </div>
            <div className="place-row small muted">
              <span>{type?.description ?? "Любой формат"}</span>
              <span>{isCovered ? "Креатив есть" : "Нет креатива"}</span>
            </div>
            {place.state !== "ACTIVE" && (
              <div className="note amber"><AlertTriangle size={17} aria-hidden /><span>Место отключено, показов здесь не будет.</span></div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function Issue({ tone, text, children }: { tone: "red" | "amber" | "lime"; text: string; children?: React.ReactNode }) {
  const Icon = tone === "red" ? CircleX : tone === "amber" ? AlertTriangle : Info;
  return (
    <div className={`note ${tone}`} style={{ flexWrap: "wrap" }}>
      <Icon size={17} aria-hidden />
      <span style={{ flex: "1 1 200px" }}>{text}</span>
      {children}
    </div>
  );
}

export type Sheet = { campaign: CampaignDetails; checks: Warnings; audit: AuditEntry[] };

export function useSheet(id: number) {
  const { actor } = useApp();
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [campaign, checks, audit] = await Promise.all([api.campaign(id, actor), api.warnings(id, actor), api.audit(id, actor)]);
      setSheet({ campaign, checks, audit });
    } catch (exc) {
      setError(exc instanceof ApiFailure ? exc.message : "Не удалось загрузить кампанию");
    }
  }, [actor, id]);

  useEffect(() => { void reload(); }, [reload]);
  return { sheet, error, reload };
}

export function SheetSkeleton() {
  return (
    <div className="page"><div className="page-inner">
      <div className="skeleton" style={{ height: 40, width: "60%" }} />
      <div className="skeleton" style={{ height: 240, borderRadius: 18 }} />
    </div></div>
  );
}

export function ModeratorComment({ audit }: { audit: AuditEntry[] }) {
  const last = [...audit].reverse().find((entry) => entry.action === "DECLINE");
  if (!last) return null;
  return (
    <section className="comment">
      <b><MessageSquareWarning size={17} aria-hidden style={{ verticalAlign: -3, marginRight: 6 }} />Комментарий модератора</b>
      <p>{last.comment}</p>
      <span className="small">{PEOPLE[last.actor] ?? last.actor}, {new Date(last.at).toLocaleDateString("ru-RU")}</span>
    </section>
  );
}

export function History({ audit }: { audit: AuditEntry[] }) {
  if (audit.length === 0) return <span className="muted">История по этой кампании не записана.</span>;
  return (
    <div className="history">
      {[...audit].reverse().map((entry, index) => (
        <div className="history-item" key={index}>
          <i aria-hidden />
          <div>
            <div>{AUDIT_ENTITIES[entry.entity] ?? entry.entity}: {AUDIT_ACTIONS[entry.action] ?? entry.action}</div>
            <span className="small muted">
              {PEOPLE[entry.actor] ?? entry.actor}, {new Date(entry.at).toLocaleDateString("ru-RU")}
              {entry.comment ? ` · ${entry.comment}` : ""}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function SheetBody({ sheet, aside, hideCreative }: { sheet: Sheet; aside?: React.ReactNode; hideCreative?: boolean }) {
  const { dictionaries } = useApp();
  const { campaign, checks, audit } = sheet;
  if (!dictionaries) return <div className="skeleton" style={{ height: 240, borderRadius: 18 }} />;
  const view = viewOfDetails(campaign);
  const topic = dictionaries.topics.find((t) => t.value === campaign.topic)?.label ?? campaign.topic;

  return (
    <div className="detail-grid">
      <div className="stack">
        <ModeratorComment audit={audit} />
        <section className="card stack">
          <div className="place-row">
            <span className="muted">{topic} · {formatPeriod(campaign)}</span>
            <StateBadge state={campaign.state} />
          </div>
          <Timeline state={campaign.state} />
          {campaign.published && <div className="note lime"><span>Показ идёт, клиенты видят кампанию.</span></div>}
        </section>
        <section className="card"><div className="section-title">Аудитория</div><AudienceBlock campaign={view} dictionaries={dictionaries} /></section>
        <section className="card"><div className="section-title">Места показа</div><PlacesBlock campaign={view} dictionaries={dictionaries} /></section>
        {(checks.warnings.length > 0 || checks.errors.length > 0) && (
          <section className="card stack">
            <div className="section-title" style={{ margin: 0 }}>Проверка</div>
            {checks.errors.map((e, i) => <Issue key={i} tone="red" text={e.message} />)}
            {checks.warnings.map((text) => <Issue key={text} tone="amber" text={text} />)}
          </section>
        )}
        <section className="card"><div className="section-title">История</div><History audit={audit} /></section>
      </div>
      <div className="stack">
        {aside}
        {!hideCreative && (
          <section className="stage-dark stack">
            <div className="section-title">Как увидит клиент</div>
            <CreativePreview campaign={view} bannerTypes={dictionaries.bannerTypes} />
          </section>
        )}
      </div>
    </div>
  );
}

const TABS = ["Основное", "Аудитория", "Размещения", "Креативы", "Проверка"] as const;

const empty: CampaignView = {
  id: null, tags: [], places: [], included: [], excluded: [], hasEnd: false,
  state: "DRAFT", published: false, banners: [], contents: [], creatives: [],
};

function Field({ label, value, onEdit }: { label: string; value?: string | number | null; onEdit: (label: string) => void }) {
  const shown = value === undefined || value === null || value === "" ? null : String(value);
  return (
    <button className="field" onClick={() => onEdit(label)} title="Изменить через ассистента">
      <span className="label">{label}</span>
      <span key={shown} className={shown ? "flash" : "empty"}>{shown ?? "Не указано"}</span>
    </button>
  );
}

export function CampaignPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { active, actor, dictionaries, dictionariesError, setDraftText, send, busy } = useApp();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Основное");
  const [saved, setSaved] = useState<{ view: CampaignView; checks: Warnings } | null>(null);

  const session = active?.session;
  const campaignId = active?.campaignId ?? null;

  useEffect(() => {
    setSaved(null);
    if (!campaignId) return;
    let cancelled = false;
    Promise.all([api.campaign(campaignId, actor), api.warnings(campaignId, actor)])
      .then(([details, checks]) => { if (!cancelled) setSaved({ view: viewOfDetails(details), checks }); })
      .catch(() => { if (!cancelled) setSaved(null); });
    return () => { cancelled = true; };
  }, [campaignId, actor, active?.revision]);

  const campaign = saved?.view ?? (session ? viewOfDraft(session) : empty);
  const errors = saved ? saved.checks.errors : session?.review.errors ?? [];
  const warnings = saved ? saved.checks.warnings : session?.review.warnings ?? [];
  const advisories = saved ? [] : session?.review.advisories ?? [];
  const progress = saved ? { percent: 100, missing: [] as string[], ready: errors.length === 0 } : session?.progress;
  const percent = progress?.percent ?? 0;

  const edit = (label: string) => setDraftText(`Измени ${label.toLowerCase()}: `);
  const replaceSegment = (name: string, excluded: boolean) =>
    setDraftText(excluded ? `Убери исключение «${name}»` : `Замени сегмент «${name}» на `);

  if (dictionariesError) {
    return (
      <aside className={`panel ${open ? "open" : ""}`}>
        <div className="card"><Issue tone="red" text={dictionariesError} /></div>
      </aside>
    );
  }

  const nextStep = !session && !campaignId ? "Опишите кампанию в диалоге"
    : (progress?.missing.length ?? 0) > 0 ? "Ответьте на вопросы ассистента"
    : errors.length > 0 ? "Исправьте ошибки в проверке"
    : campaignId ? "Кампания сохранена" : "Подтвердите создание";

  return (
    <aside className={`panel ${open ? "open" : ""}`} aria-label="Кампания">
      <button className="icon-btn panel-close" onClick={onClose} aria-label="Закрыть панель"><X size={19} /></button>

      <section className={`readiness ${percent === 100 ? "" : percent === 0 ? "dark" : ""}`}>
        <Mascot className="mascot-mini" mood={busy ? "thinking" : percent === 100 ? "happy" : "idle"} />
        <div className="readiness-top">
          <span>Готовность</span>
          <span className="readiness-value mono">{percent}%</span>
        </div>
        <div className="bar" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Готовность кампании">
          <i style={{ width: `${percent}%` }} />
        </div>
        {(progress?.missing.length ?? 0) > 0 && percent > 0 && (
          <div className="missing">{progress!.missing.map((m) => <span key={m}>{m}</span>)}</div>
        )}
        <span className="small"><b style={{ fontWeight: 600 }}>Дальше:</b> {nextStep}</span>
      </section>

      <div className="card"><Timeline state={campaign.state} /></div>

      <div className="tabs" role="tablist" aria-label="Разделы кампании">
        {TABS.map((name) => (
          <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>{name}</button>
        ))}
      </div>

      {!dictionaries ? (
        <div className="card stack"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
      ) : (
        <div className="panel-body rise" key={tab}>
          {tab === "Основное" && (
            <div className="card field-grid">
              <Field label="Название" value={campaign.name} onEdit={edit} />
              <Field label="Маркетинговое название" value={campaign.marketingName} onEdit={edit} />
              <Field label="Тематика" value={dictionaries.topics.find((t) => t.value === campaign.topic)?.label} onEdit={edit} />
              <Field label="Начало показа" value={campaign.startDate && `${formatDate(campaign.startDate)}, ${campaign.startTime ?? "время не указано"}`} onEdit={edit} />
              <Field
                label="Окончание показа"
                value={campaign.endDate ? `${formatDate(campaign.endDate)}${campaign.endTime ? `, ${campaign.endTime}` : ""}` : campaign.hasEnd ? "Бессрочно" : null}
                onEdit={edit}
              />
              <Field label="Вес" value={session?.draft.weightReasons?.length ? `${campaign.weight ?? 0} (${session.draft.weightReasons.join(", ")})` : campaign.weight ?? (session ? 0 : null)} onEdit={edit} />
              <Field label="Стартовый CTR" value={campaign.initialCtr !== undefined ? `${campaign.initialCtr}%` : session ? "15%" : null} onEdit={edit} />
              <Field label="Теги" value={campaign.tags.map((id) => dictionaries.tags.find((t) => t.id === id)?.name).filter(Boolean).join(", ")} onEdit={edit} />
            </div>
          )}

          {tab === "Аудитория" && (
            <div className="card"><AudienceBlock campaign={campaign} dictionaries={dictionaries} onReplace={replaceSegment} /></div>
          )}

          {tab === "Размещения" && <div className="card"><PlacesBlock campaign={campaign} dictionaries={dictionaries} /></div>}

          {tab === "Креативы" && (
            <div className="card"><CreativePreview campaign={campaign} bannerTypes={dictionaries.bannerTypes} /></div>
          )}

          {tab === "Проверка" && (
            <div className="card stack">
              <div className="section-title" style={{ margin: 0 }}>Проверка кампании</div>
              {!session && !campaignId && <span className="muted">Проверка начнётся, когда появятся параметры кампании.</span>}
              {(session || campaignId) && errors.length === 0 && (progress?.missing.length ?? 0) === 0 && (
                <div className="note lime"><CheckCircle2 size={17} aria-hidden /><span>Кампания готова к модерации.</span></div>
              )}
              {(session || campaignId) && errors.map((issue, index) => (
                <Issue key={index} tone="red" text={issue.message}>
                  <button className="btn secondary small" disabled={!!busy} onClick={() => send(`Исправь проблему: ${issue.message}`)}>
                    <Sparkles size={14} aria-hidden /> Исправить
                  </button>
                </Issue>
              ))}
              {warnings.map((text) => (
                <Issue key={text} tone="amber" text={text}>
                  <button className="btn secondary small" disabled={!!busy} onClick={() => send(`Помоги устранить предупреждение: ${text}`)}>
                    <Sparkles size={14} aria-hidden /> Исправить
                  </button>
                </Issue>
              ))}
              {advisories.map((a) => <Issue key={a.code} tone="lime" text={a.message} />)}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
