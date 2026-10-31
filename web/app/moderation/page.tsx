"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { MiniCreative } from "@/components/CreativePreview";
import { CreativePreview } from "@/components/CreativePreview";
import { SheetBody, SheetSkeleton, useSheet } from "@/components/Campaign";
import { useApp } from "@/components/Providers";
import { api, ApiFailure } from "@/lib";
import { formatPeriod, viewOfDetails } from "@/lib";
import type { CampaignListItem } from "@/lib";

const CHECKLIST = [
  "Тексты соответствуют условиям акции",
  "Креативы настроены для всех мест показа",
  "Аудитория соответствует продукту",
  "Ссылки ведут на нужные экраны",
];

function Decision({ id, onDone }: { id: number; onDone: () => void }) {
  const { actor, switchRole, toast } = useApp();
  const [comment, setComment] = useState("");
  const [declining, setDeclining] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());

  useEffect(() => { setChecked(new Set()); setDeclining(false); setComment(""); }, [id]);

  if (actor.role !== "campaignModerator") {
    return (
      <section className="card stack">
        <div className="section-title" style={{ margin: 0 }}>Решение модератора</div>
        <span className="muted">Одобрять и возвращать кампании может только модератор.</span>
        <button className="btn secondary" onClick={switchRole}>Войти как модератор</button>
      </section>
    );
  }

  const decide = async (name: "approve" | "decline") => {
    setFailure(null);
    try {
      await api.action(id, name, actor, name === "decline" ? { comment } : undefined);
      toast(name === "approve" ? "Кампания одобрена" : "Кампания возвращена на доработку");
      onDone();
    } catch (exc) {
      setFailure(exc instanceof ApiFailure ? exc.message : "Не удалось сохранить решение");
    }
  };

  return (
    <section className="card stack">
      <div className="section-title" style={{ margin: 0 }}>Чек-лист проверки</div>
      <div>
        {CHECKLIST.map((text, index) => (
          <label className="check" key={text}>
            <input
              type="checkbox"
              checked={checked.has(index)}
              onChange={() => setChecked((set) => {
                const next = new Set(set);
                if (!next.delete(index)) next.add(index);
                return next;
              })}
            />
            {text}
          </label>
        ))}
      </div>
      {failure && <div className="note red" role="alert"><span>{failure}</span></div>}
      {declining && (
        <textarea
          className="field-input"
          rows={3}
          autoFocus
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Что нужно исправить"
          aria-label="Комментарий модератора"
        />
      )}
      <div className="actions">
        {declining ? (
          <>
            <button className="btn danger" disabled={!comment.trim()} onClick={() => decide("decline")}>Вернуть на доработку</button>
            <button className="btn secondary" onClick={() => setDeclining(false)}>Отмена</button>
          </>
        ) : (
          <>
            <button className="btn primary" onClick={() => decide("approve")}>Одобрить</button>
            <button className="btn secondary" onClick={() => setDeclining(true)}>Вернуть на доработку</button>
          </>
        )}
      </div>
    </section>
  );
}

function Review({ id, onDone }: { id: number; onDone: () => void }) {
  const { dictionaries } = useApp();
  const { sheet, error } = useSheet(id);
  if (error) return <div className="error-card" role="alert">{error}</div>;
  if (!sheet || !dictionaries) return <SheetSkeleton />;
  return (
    <div className="review rise">
      <div className="stack">
        <section className="stage-dark stack">
          <div className="section-title">{sheet.campaign.name}</div>
          <CreativePreview campaign={viewOfDetails(sheet.campaign)} bannerTypes={dictionaries.bannerTypes} />
        </section>
        <SheetBody sheet={sheet} hideCreative />
      </div>
      <div className="stack" style={{ position: "sticky", top: 0 }}><Decision id={id} onDone={onDone} /></div>
    </div>
  );
}

export default function ModerationPage() {
  const { actor } = useApp();
  const [queue, setQueue] = useState<CampaignListItem[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.campaigns(actor)
      .then((list) => {
        const waiting = list.filter((c) => c.state === "ON_MODERATION");
        setQueue(waiting);
        setSelected(waiting[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, [actor]);

  useEffect(load, [load]);

  return (
    <div className="page">
      <div className="page-inner">
        <h1 className="page-title">Модерация</h1>
        {error && <div className="error-card" role="alert">{error}</div>}
        {!queue && !error && <div className="skeleton" style={{ height: 66, borderRadius: 14 }} />}
        {queue?.length === 0 && (
          <div className="card empty-state"><CheckCircle2 size={28} aria-hidden /><b>Очередь пуста</b><span>Все кампании проверены</span></div>
        )}
        {queue && queue.length > 0 && (
          <>
            <div className="queue">
              {queue.map((c) => (
                <button key={c.id} aria-pressed={c.id === selected} onClick={() => setSelected(c.id)} title={formatPeriod(c)}>
                  <MiniCreative fallback={c.name} />
                  <b>{c.name}</b>
                </button>
              ))}
            </div>
            {selected && <Review key={selected} id={selected} onDone={load} />}
          </>
        )}
      </div>
    </div>
  );
}
