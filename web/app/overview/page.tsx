"use client";

import Link from "next/link";
import { ArrowUpRight, CalendarClock, CheckCircle2 } from "lucide-react";
import { StateBadge } from "@/components/Campaign";
import { MiniCreative } from "@/components/CreativePreview";
import { Mascot } from "@/components/Mascot";
import { useCampaigns } from "@/components/Providers";
import { formatDate, STATE_LABELS } from "@/lib";
import type { CampaignState } from "@/lib";

const FUNNEL: CampaignState[] = ["DRAFT", "ON_MODERATION", "NEEDS_WORK", "APPROVED", "ACTIVE", "STOPPED"];
const today = () => new Date().toISOString().slice(0, 10);

function word(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  return mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? few : many;
}

export default function OverviewPage() {
  const { campaigns, error } = useCampaigns();

  if (error) return <div className="page"><div className="page-inner"><div className="error-card" role="alert">{error}</div></div></div>;
  if (!campaigns) {
    return <div className="page"><div className="page-inner"><div className="skeleton" style={{ height: 340, borderRadius: 24 }} /></div></div>;
  }

  const live = campaigns.filter((c) => c.published);
  const waiting = campaigns.filter((c) => c.state === "ON_MODERATION");
  const attention = campaigns.filter((c) => c.state === "NEEDS_WORK" || (c.checks.warnings.length > 0 && c.state === "DRAFT"));
  const upcoming = campaigns
    .filter((c) => c.startDate >= today() && !c.published)
    .sort((a, b) => a.startDate.localeCompare(b.startDate))
    .slice(0, 4);
  const count = (state: CampaignState) => campaigns.filter((c) =>
    state === "ACTIVE" ? c.state === "ACTIVE" || c.state === "ACTIVE_EDITING" : c.state === state).length;

  return (
    <div className="page">
      <div className="page-inner">
        <div className="bento">
          <section className="tile grad hero-tile span-7 rise">
            <Mascot variant="pills" />
            <div className="giant-label">Сейчас в показе</div>
            <div>
              <div className="giant">{live.length}</div>
              <div className="giant-label">{word(live.length, "кампания", "кампании", "кампаний")} из {campaigns.length}</div>
            </div>
          </section>

          <section className="tile dark span-5 rise">
            <div className="place-row">
              <h2>Ждут модератора</h2>
              <Link href="/moderation" aria-label="Открыть модерацию"><ArrowUpRight size={20} /></Link>
            </div>
            <div className="giant" style={{ fontSize: "clamp(64px, 8vw, 120px)" }}>{waiting.length}</div>
            <div>
              {waiting.slice(0, 2).map((c) => (
                <Link key={c.id} href="/moderation" className="list-link">
                  <MiniCreative banner={c.banners[0]} fallback={c.name} />
                  <span style={{ minWidth: 0 }}><b>{c.name}</b><span className="small muted">с {formatDate(c.startDate)}</span></span>
                </Link>
              ))}
            </div>
          </section>

          <section className="tile span-12 rise">
            <h2>Конвейер</h2>
            <div className="funnel">
              {FUNNEL.map((state) => (
                <Link key={state} href={`/campaigns?state=${state}`}>
                  <b className="mono">{count(state)}</b>
                  <span>{state === "ACTIVE" ? "В показе" : STATE_LABELS[state]}</span>
                </Link>
              ))}
            </div>
          </section>

          <section className="tile span-6 rise">
            <h2>Нужно внимание</h2>
            {attention.length === 0 && <div className="note lime"><CheckCircle2 size={17} aria-hidden /><span>Всё в порядке.</span></div>}
            <div>
              {attention.slice(0, 4).map((c) => (
                <Link key={c.id} href={`/campaigns/${c.id}`} className="list-link">
                  <MiniCreative banner={c.banners[0]} fallback={c.name} />
                  <span style={{ minWidth: 0 }}>
                    <b>{c.name}</b>
                    <span className="small muted">{c.state === "NEEDS_WORK" ? "Вернул модератор" : c.checks.warnings[0]}</span>
                  </span>
                  <StateBadge state={c.state} />
                </Link>
              ))}
            </div>
          </section>

          <section className="tile span-6 rise">
            <h2><CalendarClock size={19} aria-hidden style={{ verticalAlign: -3, marginRight: 8 }} />Скоро старт</h2>
            <div>
              {upcoming.map((c) => (
                <Link key={c.id} href={`/campaigns/${c.id}`} className="list-link">
                  <MiniCreative banner={c.banners[0]} fallback={c.name} />
                  <span style={{ minWidth: 0 }}><b>{c.name}</b><span className="small muted">{formatDate(c.startDate)}</span></span>
                  <StateBadge state={c.state} />
                </Link>
              ))}
              {upcoming.length === 0 && <span className="muted">Ближайших запусков нет.</span>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
