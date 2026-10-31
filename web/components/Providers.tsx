"use client";

import { type Actor, ApiFailure, type CampaignDetails, type ConfirmAction, type Dictionaries, type Role, type SessionState, type StreamEvent, type Warnings, agent, api } from "@/lib";
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

export type ChatItem =
  | { id: string; kind: "user" | "assistant" | "error"; text: string }
  | { id: string; kind: "confirm"; actions: ConfirmAction[]; review?: SessionState["review"]; resolved?: "approved" | "rejected" }
  | { id: string; kind: "success"; campaignId: number | null };

export type Dialog = {
  id: string;
  title: string;
  items: ChatItem[];
  session?: SessionState;
  campaignId?: number;
  revision: number; // растёт после каждого хода, чтобы панель перечитала кампанию
};

const ACTORS: Record<Role, Actor> = {
  campaignManager: { user: "ivanov.p", role: "campaignManager" },
  campaignModerator: { user: "petrova.m", role: "campaignModerator" },
};
const STORAGE_KEY = "campaign-assistant:v1";

type AppContext = {
  actor: Actor;
  switchRole: () => void;
  dictionaries: Dictionaries | null;
  dictionariesError: string | null;
  dialogs: Dialog[];
  active: Dialog | null;
  openDialog: (id: string) => void;
  newDialog: () => void;
  busy: string | null;
  send: (text: string, campaignId?: number) => Promise<void>;
  decide: (item: ChatItem, approved: boolean, edits?: Record<string, string>) => Promise<void>;
  draftText: string;
  setDraftText: (text: string) => void;
  toast: (text: string) => void;
};

const Context = createContext<AppContext | null>(null);

export function useApp(): AppContext {
  const value = useContext(Context);
  if (!value) throw new Error("useApp вне Providers");
  return value;
}

const uid = () => Math.random().toString(36).slice(2, 10);

function titleOf(text: string): string {
  return text.length > 44 ? `${text.slice(0, 44).trim()}…` : text;
}

function readSaved(): { role?: Role; dialogs?: Dialog[] } {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function Providers({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>("campaignManager");
  const [dialogs, setDialogs] = useState<Dialog[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dictionaries, setDictionaries] = useState<Dictionaries | null>(null);
  const [dictionariesError, setDictionariesError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<{ id: string; text: string }[]>([]);
  const [draftText, setDraftText] = useState("");
  const [loaded, setLoaded] = useState(false);

  const actor = ACTORS[role];
  const dialogsRef = useRef(dialogs);
  dialogsRef.current = dialogs;

  useEffect(() => {
    const saved = readSaved();
    if (saved.role) setRole(saved.role);
    if (saved.dialogs) setDialogs(saved.dialogs);
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ role, dialogs: dialogs.slice(0, 12) }));
    } catch {
      /* история диалогов только удобство */
    }
  }, [role, dialogs, loaded]);

  useEffect(() => {
    api.dictionaries(actor).then(setDictionaries).catch((e: Error) => setDictionariesError(e.message));
  }, [actor]);

  const toast = useCallback((text: string) => {
    const id = uid();
    setToasts((list) => [...list, { id, text }]);
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 3200);
  }, []);

  const update = useCallback((id: string, change: (dialog: Dialog) => Dialog) => {
    setDialogs((list) => list.map((d) => (d.id === id ? change(d) : d)));
  }, []);

  const addItems = useCallback(
    (id: string, ...items: ChatItem[]) => update(id, (d) => ({ ...d, items: [...d.items, ...items] })),
    [update],
  );

  const consume = useCallback(
    (dialogId: string, onDone?: (failed: boolean) => void) => (event: StreamEvent) => {
      if (event.type === "status") {
        setBusy(event.label);
        return;
      }
      const { turn, session } = event;
      const items: ChatItem[] = [];
      if (turn.text) items.push({ id: uid(), kind: "assistant", text: turn.text });
      if (turn.confirmation) {
        items.push({ id: uid(), kind: "confirm", actions: turn.confirmation, review: session?.review });
      }
      if (turn.error) items.push({ id: uid(), kind: "error", text: turn.error });
      update(dialogId, (d) => ({
        ...d,
        session: session ?? d.session,
        campaignId: session?.draft.campaignId ?? d.campaignId,
        items: [...d.items, ...items],
        revision: d.revision + 1,
      }));
      onDone?.(Boolean(turn.error));
    },
    [update],
  );

  const guarded = useCallback(
    async (dialogId: string, work: () => Promise<void>) => {
      setBusy("Думаю над ответом");
      try {
        await work();
      } catch (exc) {
        const text = exc instanceof ApiFailure ? exc.message : "Связь прервалась. Попробуйте ещё раз.";
        addItems(dialogId, { id: uid(), kind: "error", text });
      } finally {
        setBusy(null);
      }
    },
    [addItems],
  );

  const send = useCallback(
    async (text: string, campaignId?: number) => {
      let dialog = dialogsRef.current.find((d) => d.id === activeId);
      if (!dialog) {
        dialog = { id: uid(), title: titleOf(text), items: [], revision: 0, campaignId };
        const created = dialog;
        setDialogs((list) => [created, ...list]);
        setActiveId(created.id);
      }
      const dialogId = dialog.id;
      update(dialogId, (d) => ({
        ...d,
        items: [
          ...d.items.map((item) => (item.kind === "confirm" && !item.resolved ? { ...item, resolved: "rejected" as const } : item)),
          { id: uid(), kind: "user", text },
        ],
      }));
      const existing = dialog.session;
      await guarded(dialogId, async () => {
        const session = existing ?? (await agent.createSession(actor));
        if (!existing) update(dialogId, (d) => ({ ...d, session }));
        await agent.send(session.id, text, consume(dialogId));
      });
    },
    [activeId, actor, consume, guarded, update],
  );

  const decide = useCallback(
    async (item: ChatItem, approved: boolean, edits?: Record<string, string>) => {
      const dialog = dialogsRef.current.find((d) => d.id === activeId);
      if (!dialog?.session || item.kind !== "confirm") return;
      const dialogId = dialog.id;
      update(dialogId, (d) => ({
        ...d,
        items: d.items.map((i) => (i.id === item.id ? ({ ...i, resolved: approved ? "approved" : "rejected" } as ChatItem) : i)),
      }));
      const toModeration = item.actions.find((a) => a.tool === "to_moderation");
      await guarded(dialogId, () =>
        agent.decide(dialog.session!.id, approved, consume(dialogId, (failed) => {
          if (!approved || failed) return;
          toast("Изменения сохранены");
          if (toModeration) {
            const campaignId = Number(toModeration.input.campaignId) || null;
            addItems(dialogId, { id: uid(), kind: "success", campaignId });
          }
        }), edits),
      );
    },
    [activeId, addItems, consume, guarded, toast, update],
  );

  const value = useMemo<AppContext>(
    () => ({
      actor,
      switchRole: () => {
        setRole((r) => (r === "campaignManager" ? "campaignModerator" : "campaignManager"));
        setActiveId(null);
      },
      dictionaries,
      dictionariesError,
      dialogs,
      active: dialogs.find((d) => d.id === activeId) ?? null,
      openDialog: setActiveId,
      newDialog: () => setActiveId(null),
      busy,
      send,
      decide,
      draftText,
      setDraftText,
      toast,
    }),
    [actor, activeId, busy, decide, dialogs, dictionaries, dictionariesError, draftText, send, toast],
  );

  return (
    <Context.Provider value={value}>
      <div className="app">{children}</div>
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast">{t.text}</div>
        ))}
      </div>
    </Context.Provider>
  );
}

export type CampaignRow = CampaignDetails & { checks: Warnings };

export function useCampaigns() {
  const { actor } = useApp();
  const [campaigns, setCampaigns] = useState<CampaignRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.campaigns(actor)
      .then((list) => Promise.all(list.map(async (c) => {
        const [details, checks] = await Promise.all([api.campaign(c.id, actor), api.warnings(c.id, actor)]);
        return { ...details, checks };
      })))
      .then(setCampaigns)
      .catch((e: Error) => setError(e.message));
  }, [actor]);

  return { campaigns, error };
}
