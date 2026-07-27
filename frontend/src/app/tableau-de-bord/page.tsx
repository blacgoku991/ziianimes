"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Nav, euros } from "@/components/Nav";
import { api } from "@/lib/api";
import type { Dashboard, Session } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [data, setData] = useState<Dashboard | null>(null);
  const [days, setDays] = useState(30);

  useEffect(() => {
    (async () => {
      try {
        setSession(await api.me());
        setData(await api.dashboard(days));
      } catch {
        router.replace("/login");
      }
    })();
  }, [days, router]);

  if (!data) return <p className="text-sm text-muted">Chargement…</p>;
  const { overview } = data;

  return (
    <main>
      <Nav session={session} />

      <div className="mb-4 flex items-center gap-2 text-sm">
        <span className="text-muted">Période :</span>
        {[7, 30, 90, 365].map((value) => (
          <button
            key={value}
            className={`rounded-md px-2 py-1 text-xs ${
              days === value ? "bg-ink text-white" : "btn-ghost"
            }`}
            onClick={() => setDays(value)}
          >
            {value} j
          </button>
        ))}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Articles vendus" value={String(overview.sold_count)} />
        <Tile label="Chiffre d'affaires" value={euros(overview.revenue_cents)} />
        <Tile
          label="Marge nette"
          value={euros(overview.margin_cents)}
          hint={`${overview.margin_pct} % du net encaissé`}
        />
        <Tile
          label="Délai moyen de vente"
          value={
            overview.average_days_to_sale !== null
              ? `${overview.average_days_to_sale} j`
              : "—"
          }
        />
        <Tile label="Annonces en ligne" value={String(overview.live_publications)} />
        <Tile label="Articles en stock" value={String(overview.articles_in_stock)} />
        <Tile
          label="Capital immobilisé"
          value={euros(overview.capital_immobilise_cents)}
        />
        <Tile
          label="Coût IA"
          value={`${(overview.ai_cost_micros / 1_000_000).toFixed(2)} €`}
          hint="coût variable réel sur la période"
        />
      </div>

      <p className="mb-6 text-xs text-muted">
        Tous les montants sont <strong>nets de frais</strong> : commissions,
        frais d&apos;encaissement et port à votre charge sont déduits. Les
        annonces sont synchronisées toutes les{" "}
        {Math.round(data.sync_interval_seconds / 60)} minutes — c&apos;est la
        fenêtre pendant laquelle une pièce vendue peut rester visible ailleurs.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card">
          <p className="label mb-2">Performance par compte / niche</p>
          {data.by_account.length === 0 ? (
            <p className="text-sm text-muted">Pas encore de vente.</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {data.by_account.map((row) => (
                  <tr key={row.account_id} className="border-b border-line last:border-0">
                    <td className="py-2">
                      {row.label}
                      <span className="text-xs text-muted">
                        {row.niche ? ` · ${row.niche}` : ""}
                      </span>
                    </td>
                    <td className="py-2 text-right text-xs">{row.sold_count} vendus</td>
                    <td className="py-2 text-right text-xs font-medium">
                      {euros(row.margin_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card">
          <p className="label mb-2">Marques les plus rentables</p>
          <p className="mb-2 text-[11px] text-muted">
            Classées par marge, pas par volume : une marque qui part vite à
            petite marge occupe du temps sans rapporter.
          </p>
          {data.top_brands.length === 0 ? (
            <p className="text-sm text-muted">Pas encore de vente.</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {data.top_brands.map((row) => (
                  <tr key={row.brand} className="border-b border-line last:border-0">
                    <td className="py-2">{row.brand}</td>
                    <td className="py-2 text-right text-xs">{row.sold_count} vendus</td>
                    <td className="py-2 text-right text-xs font-medium">
                      {euros(row.margin_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </main>
  );
}

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card">
      <p className="label">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-[11px] text-muted">{hint}</p>}
    </div>
  );
}
