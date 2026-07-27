"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Nav, euros } from "@/components/Nav";
import { api } from "@/lib/api";
import type { QuickReply, Session, Thread, ThreadMessage } from "@/lib/types";

export default function InboxPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [active, setActive] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setThreads(await api.inbox());
    setQuickReplies(await api.quickReplies());
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setSession(await api.me());
        await load();
      } catch {
        router.replace("/login");
      } finally {
        setLoading(false);
      }
    })();
  }, [load, router]);

  async function open(thread: Thread) {
    setActive(thread);
    setMessages(await api.threadMessages(thread.id));
    setThreads(await api.inbox());
  }

  async function send() {
    if (!active || !draft.trim()) return;
    await api.reply(active.id, draft);
    setDraft("");
    setMessages(await api.threadMessages(active.id));
  }

  if (loading) return <p className="text-sm text-muted">Chargement…</p>;

  return (
    <main>
      <Nav session={session} />

      <div className="grid gap-4 md:grid-cols-[320px_1fr]">
        <aside className="space-y-2">
          {threads.length === 0 && (
            <p className="card text-sm text-muted">
              Aucun message. La boîte se remplit à la synchronisation des comptes.
            </p>
          )}
          {threads.map((thread) => (
            <button
              key={thread.id}
              onClick={() => open(thread)}
              className={`card w-full text-left ${
                active?.id === thread.id ? "border-neutral-400" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">
                  {thread.counterparty_name ?? "Interlocuteur"}
                </p>
                {thread.unread_count > 0 && (
                  <span className="rounded-full bg-ink px-2 text-[10px] text-white">
                    {thread.unread_count}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted">
                {thread.platform} · {thread.account_label}
              </p>
              {thread.best_offer_cents && (
                <p className="mt-1 text-xs font-medium text-emerald-700">
                  offre : {euros(thread.best_offer_cents)}
                </p>
              )}
              <p className="mt-1 line-clamp-2 text-xs text-muted">
                {thread.last_message_preview}
              </p>
            </button>
          ))}
        </aside>

        <section className="card">
          {!active ? (
            <p className="text-sm text-muted">
              Sélectionnez une conversation.
            </p>
          ) : (
            <>
              <p className="mb-3 border-b border-line pb-2 text-sm font-medium">
                {active.counterparty_name ?? "Interlocuteur"}{" "}
                <span className="text-xs text-muted">
                  · {active.platform} · {active.account_label}
                </span>
              </p>
              <div className="mb-4 max-h-96 space-y-2 overflow-y-auto">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                      message.direction === "outbound"
                        ? "ml-auto bg-ink text-white"
                        : "bg-neutral-100"
                    }`}
                  >
                    {message.body}
                    {message.offer_price_cents && (
                      <p className="mt-1 text-[11px] opacity-80">
                        offre détectée : {euros(message.offer_price_cents)}
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <div className="mb-2 flex flex-wrap gap-1">
                {quickReplies.map((reply) => (
                  <button
                    key={reply.id}
                    className="btn-ghost px-2 py-1 text-[11px]"
                    onClick={() => setDraft(reply.body)}
                  >
                    {reply.label}
                  </button>
                ))}
              </div>

              <div className="flex gap-2">
                <textarea
                  className="field"
                  rows={3}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Votre réponse…"
                />
                <button className="btn-primary shrink-0" onClick={send}>
                  Envoyer
                </button>
              </div>
              <p className="mt-2 text-[11px] text-muted">
                L&apos;envoi passe par la file : il compte comme une action et
                respecte la cadence du compte.
              </p>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
