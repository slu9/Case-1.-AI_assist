"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ClipboardCheck, History, LayoutDashboard, Plus, Rows3, Sparkles } from "lucide-react";
import { api } from "@/lib";
import { PEOPLE, STATE_TONES } from "@/lib";
import type { CampaignListItem } from "@/lib";
import { useApp } from "@/components/Providers";

const LINKS = [
  { href: "/", label: "Ассистент", icon: Sparkles },
  { href: "/overview", label: "Обзор", icon: LayoutDashboard },
  { href: "/campaigns", label: "Кампании", icon: Rows3 },
  { href: "/moderation", label: "Модерация", icon: ClipboardCheck },
];

function Nav({ waiting }: { waiting: number }) {
  const pathname = usePathname();
  return (
    <nav className="nav" aria-label="Разделы">
      {LINKS.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link key={href} href={href} className={active ? "active" : ""} aria-current={active ? "page" : undefined} aria-label={label}>
            <Icon size={17} aria-hidden />
            {label}
            {href === "/moderation" && waiting > 0 && <span className="count">{waiting}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

export function TopBar() {
  const { actor, switchRole, dialogs, active, openDialog, newDialog } = useApp();
  const router = useRouter();
  const pathname = usePathname();
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([]);
  const [open, setOpen] = useState(false);
  const popover = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.campaigns(actor).then(setCampaigns).catch(() => setCampaigns([]));
  }, [actor, pathname, dialogs.length]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        newDialog();
        router.push("/");
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newDialog, router]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!popover.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  const stateOf = (id?: number) => campaigns.find((c) => c.id === id)?.state;
  const name = PEOPLE[actor.user];
  const waiting = campaigns.filter((c) => c.state === "ON_MODERATION").length;

  return (
    <header className="topbar">
      <Link href="/" className="brand" aria-label="Campaign Assistant">
        <span className="brand-mark"><Sparkles size={18} aria-hidden /></span>
        <span className="brand-name">Campaign Assistant</span>
      </Link>

      <Suspense fallback={null}><Nav waiting={waiting} /></Suspense>

      <div className="top-actions" ref={popover}>
        {dialogs.length > 0 && (
          <button className="top-btn dialogs-btn" aria-expanded={open} onClick={() => setOpen(!open)} title="Последние диалоги">
            <History size={17} aria-hidden /> {dialogs.length}
          </button>
        )}
        {open && (
          <div className="popover">
            <div className="side-label">Последние диалоги</div>
            {dialogs.slice(0, 8).map((dialog) => {
              const state = stateOf(dialog.campaignId);
              return (
                <button
                  key={dialog.id}
                  className={`dialog-link ${dialog.id === active?.id ? "active" : ""}`}
                  onClick={() => { openDialog(dialog.id); setOpen(false); router.push("/"); }}
                >
                  <span className={`dot ${state ? STATE_TONES[state] : ""}`} aria-hidden />
                  <span>{dialog.title}</span>
                </button>
              );
            })}
          </div>
        )}
        <button className="new-campaign" onClick={() => { newDialog(); router.push("/"); }} title="Новая кампания (⌘K)" aria-label="Новая кампания">
          <Plus size={18} aria-hidden /> Новая кампания
        </button>
        <button className="profile" onClick={switchRole} title="Переключить роль">
          <span className="avatar">{name.split(" ").map((p) => p[0]).join("")}</span>
          <span className="profile-text">
            <div className="profile-name">{name}</div>
            <div className="profile-role">{actor.role === "campaignManager" ? "Менеджер" : "Модератор"}</div>
          </span>
        </button>
      </div>
    </header>
  );
}
