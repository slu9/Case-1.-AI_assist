"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Radio, Search } from "lucide-react";
import { MiniCreative } from "@/components/CreativePreview";
import { useApp } from "@/components/Providers";
import { useCampaigns, type CampaignRow } from "@/components/Providers";
import { formatPeriod, PEOPLE } from "@/lib";
import type { CampaignState } from "@/lib";

const LANES: { title: string; states: CampaignState[] }[] = [
  { title: "Черновики", states: ["DRAFT"] },
  { title: "На модерации", states: ["ON_MODERATION"] },
  { title: "Доработка", states: ["NEEDS_WORK"] },
  { title: "Одобрены", states: ["APPROVED"] },
  { title: "В показе", states: ["ACTIVE", "ACTIVE_EDITING"] },
  { title: "Остановлены", states: ["STOPPED"] },
];

function Poster({ campaign }: { campaign: CampaignRow }) {
  return (
    <Link href={`/campaigns/${campaign.id}`} className="poster rise">
      <div style={{ position: "relative" }}>
        {campaign.published && <span className="live"><i aria-hidden /> Показ идёт</span>}
        <MiniCreative banner={campaign.banners[0]} fallback={campaign.name} />
      </div>
      <div className="poster-body">
        <b>{campaign.name}</b>
        <span className="small muted">{formatPeriod(campaign)}</span>
      </div>
    </Link>
  );
}

function Board() {
  const { dictionaries } = useApp();
  const { campaigns, error } = useCampaigns();
  const initial = useSearchParams().get("state") ?? "";
  const [query, setQuery] = useState("");
  const [state, setState] = useState(initial);
  const [topic, setTopic] = useState("");
  const [author, setAuthor] = useState("");
  const [from, setFrom] = useState("");
  const [liveOnly, setLiveOnly] = useState(false);

  useEffect(() => setState(initial), [initial]);

  const shown = useMemo(() => (campaigns ?? []).filter((c) =>
    (!query || c.name.toLowerCase().includes(query.toLowerCase()))
    && (!topic || c.topic === topic)
    && (!author || c.author === author)
    && (!from || c.startDate >= from)
    && (!liveOnly || c.published)), [author, campaigns, from, liveOnly, query, topic]);

  const lanes = LANES.filter((lane) => !state || lane.states.includes(state as CampaignState));
  const authors = [...new Set((campaigns ?? []).map((c) => c.author))];

  return (
    <div className="page">
      <div className="page-inner">
        <h1 className="page-title">Кампании</h1>
        <div className="filter-row">
          <label className="search">
            <Search size={17} aria-hidden />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти кампанию" aria-label="Поиск по названию" />
          </label>
          <select className="select" value={state} onChange={(e) => setState(e.target.value)} aria-label="Этап">
            <option value="">Все этапы</option>
            {LANES.map((lane) => <option key={lane.title} value={lane.states[0]}>{lane.title}</option>)}
          </select>
          <select className="select" value={topic} onChange={(e) => setTopic(e.target.value)} aria-label="Тематика">
            <option value="">Все тематики</option>
            {dictionaries?.topics.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <select className="select" value={author} onChange={(e) => setAuthor(e.target.value)} aria-label="Автор">
            <option value="">Все авторы</option>
            {authors.map((a) => <option key={a} value={a}>{PEOPLE[a] ?? a}</option>)}
          </select>
          <input className="select" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Старт не раньше" />
          <button className="chip-button" aria-pressed={liveOnly} onClick={() => setLiveOnly(!liveOnly)} style={liveOnly ? { background: "var(--lime)" } : undefined}>
            <Radio size={14} aria-hidden style={{ verticalAlign: -2, marginRight: 5 }} />Сейчас в показе
          </button>
        </div>

        {error && <div className="error-card" role="alert">{error}</div>}
        {!campaigns && !error && <div className="skeleton" style={{ height: 320, borderRadius: 24 }} />}
        {campaigns && (
          <div className="board" style={lanes.length === 1 ? { gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" } : undefined}>
            {lanes.map((lane) => {
              const items = shown.filter((c) => lane.states.includes(c.state));
              return (
                <section key={lane.title} className="lane" style={lanes.length === 1 ? { gridColumn: "1 / -1" } : undefined}>
                  <div className="lane-head">{lane.title} <span>{items.length}</span></div>
                  <div style={lanes.length === 1 ? { display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" } : { display: "grid", gap: 12 }}>
                    {items.map((c) => <Poster key={c.id} campaign={c} />)}
                    {items.length === 0 && <div className="lane-empty">Пусто</div>}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function CampaignsPage() {
  return <Suspense fallback={null}><Board /></Suspense>;
}
