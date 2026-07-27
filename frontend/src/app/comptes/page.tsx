"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Nav } from "@/components/Nav";
import { api } from "@/lib/api";
import type { AccountHealth, Session } from "@/lib/types";

const PLATFORMS = [
  { value: "vinted", label: "Vinted (session navigateur)" },
  { value: "leboncoin", label: "Leboncoin (OAuth)" },
  { value: "depop", label: "Depop (OAuth)" },
  { value: "ebay", label: "eBay (OAuth)" },
];

export default function AccountsPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [accounts, setAccounts] = useState<AccountHealth[]>([]);
  const [platform, setPlatform] = useState("vinted");
  const [label, setLabel] = useState("");
  const [niche, setNiche] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setAccounts(await api.accountsHealth());
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

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.createAccount({ platform, label, niche: niche || null });
      setLabel("");
      setNiche("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Création impossible");
    }
  }

  async function onConnect(accountId: string) {
    const raw = window.prompt(
      "Collez les cookies de session exportés depuis votre navigateur (JSON), " +
        "ou le jeton OAuth pour les plateformes à API.",
    );
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      const payload = Array.isArray(parsed)
        ? { cookies: parsed }
        : (parsed as Record<string, unknown>);
      await api.storeCredentials(accountId, payload);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Format non reconnu");
    }
  }

  if (loading) return <p className="text-sm text-muted">Chargement…</p>;

  const noticeAccepted = Boolean(session?.workspace.automation_notice_accepted_at);

  return (
    <main>
      <Nav session={session} />

      <section className="card mb-6 border-amber-300 bg-amber-50 text-sm">
        <p className="font-medium">Automatisation et conditions d&apos;utilisation</p>
        <p className="mt-1 text-xs leading-relaxed text-neutral-800">
          L&apos;automatisation des publications est contraire aux conditions
          d&apos;utilisation de certaines plateformes. Le risque de restriction
          de compte est porté par vous. Le mode brouillon — où vous donnez
          vous-même la validation finale — reste disponible en permanence et
          constitue le comportement par défaut. Tant que cet avertissement
          n&apos;est pas accepté, toute publication est forcée en brouillon.
        </p>
        <button
          className="btn-ghost mt-2 text-xs"
          onClick={async () => {
            await api.acceptAutomationNotice(!noticeAccepted);
            setSession(await api.me());
          }}
        >
          {noticeAccepted
            ? "Avertissement accepté — révoquer"
            : "J'ai lu et j'accepte le risque"}
        </button>
      </section>

      <form onSubmit={onCreate} className="card mb-6 flex flex-wrap gap-2">
        <select
          className="field max-w-xs"
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
        >
          {PLATFORMS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <input
          className="field max-w-xs"
          placeholder="Nom du compte (ex. Vinted vintage)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          required
        />
        <input
          className="field max-w-[10rem]"
          placeholder="Niche"
          value={niche}
          onChange={(e) => setNiche(e.target.value)}
        />
        <button className="btn-primary" type="submit">
          Rattacher
        </button>
      </form>

      <p className="mb-3 text-xs text-muted">
        Vous rattachez des comptes que vous possédez déjà. L&apos;outil ne crée
        aucun compte et ne contourne aucun contrôle anti-robot.
      </p>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="space-y-3">
        {accounts.map((account) => (
          <div key={account.id} className="card flex items-center justify-between">
            <div>
              <p className="font-medium">
                {account.label}{" "}
                <span className="text-xs text-muted">
                  {account.platform}
                  {account.niche ? ` · ${account.niche}` : ""}
                </span>
              </p>
              <p className="mt-1 text-xs">
                <span
                  className={
                    account.status === "active" ? "text-emerald-700" : "text-amber-700"
                  }
                >
                  {account.status === "active"
                    ? "connecté"
                    : "reconnexion nécessaire"}
                </span>
                <span className="text-muted">
                  {" "}
                  · {account.daily_action_count}/{account.daily_action_cap} actions
                  aujourd&apos;hui
                </span>
              </p>
              {account.last_error && (
                <p className="mt-1 text-xs text-red-600">{account.last_error}</p>
              )}
              {account.health_check_overdue && (
                <p className="mt-1 text-xs text-muted">
                  contrôle de santé jamais effectué ou trop ancien
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <button className="btn-ghost text-xs" onClick={() => onConnect(account.id)}>
                {account.has_credentials ? "Reconnecter" : "Connecter"}
              </button>
              <button
                className="btn-ghost text-xs text-red-600"
                onClick={async () => {
                  await api.deleteAccount(account.id);
                  await load();
                }}
              >
                Retirer
              </button>
            </div>
          </div>
        ))}
        {accounts.length === 0 && (
          <p className="card text-sm text-muted">Aucun compte rattaché.</p>
        )}
      </div>
    </main>
  );
}
