"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Sparkles } from "lucide-react";
import { StateBadge } from "@/components/Campaign";
import { SheetBody, SheetSkeleton, useSheet } from "@/components/Campaign";
import { CreativeArt, briefOf } from "@/components/CreativePreview";
import { useApp } from "@/components/Providers";
import { api, ApiFailure } from "@/lib";
import { formatPeriod } from "@/lib";
import type { CampaignState } from "@/lib";

const EDITABLE: CampaignState[] = ["DRAFT", "NEEDS_WORK", "APPROVED", "ACTIVE", "ACTIVE_EDITING"];
const TO_MODERATION: CampaignState[] = ["DRAFT", "NEEDS_WORK", "ACTIVE_EDITING"];

export default function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number(use(params).id);
  const { actor, toast, newDialog } = useApp();
  const { sheet, error, reload } = useSheet(id);
  const [failure, setFailure] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const router = useRouter();

  if (error) return <div className="page"><div className="page-inner"><div className="error-card" role="alert">{error}</div></div></div>;
  if (!sheet) return <SheetSkeleton />;
  const { campaign } = sheet;

  const run = async (name: string, done: string) => {
    setWorking(true);
    setFailure(null);
    try {
      await api.action(id, name, actor);
      toast(done);
      await reload();
    } catch (exc) {
      setFailure(exc instanceof ApiFailure ? exc.message : "Не удалось выполнить действие");
    } finally {
      setWorking(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Удалить кампанию «${campaign.name}»? Отменить это нельзя.`)) return;
    try {
      await api.remove(id, actor);
      toast("Кампания удалена");
      router.push("/campaigns");
    } catch (exc) {
      setFailure(exc instanceof ApiFailure ? exc.message : "Не удалось удалить кампанию");
    }
  };

  const isManager = actor.role === "campaignManager";
  const actions = (
    <section className="card stack">
      <div className="section-title" style={{ margin: 0 }}>Действия</div>
      {failure && <div className="note red" role="alert"><span>{failure}</span></div>}
      {!isManager && <span className="muted small">Вы вошли как модератор. Решение принимается на экране модерации.</span>}
      {isManager && (
        <div className="actions">
          {EDITABLE.includes(campaign.state) && (
            <button className="btn primary" onClick={() => { newDialog(); router.push(`/?campaign=${id}`); }}>
              <Sparkles size={16} aria-hidden /> Открыть в ассистенте
            </button>
          )}
          {TO_MODERATION.includes(campaign.state) && (
            <button className="btn secondary" disabled={working} onClick={() => run("to-moderation", "Кампания отправлена на модерацию")}>На модерацию</button>
          )}
          {campaign.state === "APPROVED" && (
            <button className="btn primary" disabled={working} onClick={() => run("activate", "Показ запущен")}>Запустить показ</button>
          )}
          {campaign.published && (
            <button className="btn danger" disabled={working} onClick={() => run("stop", "Показ остановлен")}>Остановить показ</button>
          )}
          {(campaign.state === "DRAFT" || campaign.state === "NEEDS_WORK") && !campaign.published && (
            <button className="btn danger" onClick={remove}>Удалить</button>
          )}
        </div>
      )}
      {campaign.state === "ON_MODERATION" && <span className="muted small">Кампания ждёт решения модератора. Редактировать её сейчас нельзя.</span>}
      {campaign.state === "STOPPED" && <span className="muted small">Остановленную кампанию нельзя возобновить или изменить.</span>}
    </section>
  );

  return (
    <div className="page">
      <div className="page-inner">
        <Link href="/campaigns" className="back"><ArrowLeft size={15} aria-hidden /> Все кампании</Link>
        <section className="cover rise">
          <div className="cover-art"><CreativeArt seed={campaign.banners[0] ? briefOf(campaign.banners[0].content) : campaign.name} /></div>
          <span><StateBadge state={campaign.state} /></span>
          <h1>{campaign.name}</h1>
          <span>{formatPeriod(campaign)}</span>
        </section>
        <SheetBody sheet={sheet} aside={actions} />
      </div>
    </div>
  );
}
