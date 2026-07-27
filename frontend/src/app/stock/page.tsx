"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Nav, euros } from "@/components/Nav";
import { api } from "@/lib/api";
import type { Session, StaleSuggestion, StockRow, StockSummary } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  draft: "brouillon",
  listed: "en ligne",
  reserved: "réservé",
  sold: "vendu",
  returned: "retourné",
  withdrawn: "retiré",
};

export default function StockPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [rows, setRows] = useState<StockRow[]>([]);
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [stale, setStale] = useState<StaleSuggestion[]>([]);
  const [search, setSearch] = useState("");
  const [staleOnly, setStaleOnly] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const params: Record<string, string> = {};
    if (search) params.search = search;
    if (staleOnly) params.stale_only = "true";
    const data = await api.stock(params);
    setRows(data.items);
    setSummary(data.summary);
    setStale(await api.staleListings());
  }, [search, staleOnly]);

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

  if (loading) return <p className="text-sm text-muted">Chargement…</p>;

  return (
    <main>
      <Nav session={session} />

      {summary && (
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="card">
            <p className="label">Articles</p>
            <p className="text-2xl font-semibold">{summary.total}</p>
          </div>
          <div className="card">
            <p className="label">En ligne</p>
            <p className="text-2xl font-semibold">{summary.by_status.listed ?? 0}</p>
          </div>
          <div className="card">
            <p className="label">Vendus</p>
            <p className="text-2xl font-semibold">{summary.by_status.sold ?? 0}</p>
          </div>
          <div className="card">
            <p className="label">Capital immobilisé</p>
            <p className="text-2xl font-semibold">
              {euros(summary.capital_immobilise_cents)}
            </p>
          </div>
        </div>
      )}

      {stale.length > 0 && (
        <section className="card mb-6 border-amber-300 bg-amber-50">
          <p className="mb-2 text-sm font-medium">
            {stale.length} annonce(s) dormante(s) — baisse suggérée
          </p>
          <ul className="space-y-1 text-xs text-neutral-700">
            {stale.slice(0, 5).map((item) => (
              <li key={item.article_id}>
                <span className="font-medium">{item.title ?? item.sku}</span> ·{" "}
                {item.reason} · {euros(item.current_price_cents)} →{" "}
                {euros(item.suggested_price_cents)}{" "}
                <span className="text-muted">
                  (plancher {euros(item.floor_cents)})
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <form
        className="card mb-4 flex flex-wrap items-center gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <input
          className="field max-w-xs"
          placeholder="Rechercher (titre, marque, réf.)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={staleOnly}
            onChange={(e) => setStaleOnly(e.target.checked)}
          />
          dormants uniquement
        </label>
        <button className="btn-ghost" type="submit">
          Filtrer
        </button>
      </form>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-line bg-neutral-50 text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="p-3">Article</th>
              <th className="p-3">Statut</th>
              <th className="p-3">Coût</th>
              <th className="p-3">Prix</th>
              <th className="p-3">Marge nette</th>
              <th className="p-3">Plateformes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b border-line last:border-0">
                <td className="p-3">
                  <Link href={`/articles/${row.id}`} className="font-medium hover:underline">
                    {row.title ?? "Sans titre"}
                  </Link>
                  <p className="text-xs text-muted">
                    {row.sku} · {row.brand ?? "—"} · {row.photo_count} photo(s)
                  </p>
                  {row.duplicate_platform_warning.length > 0 && (
                    <p className="mt-1 text-xs text-red-600">
                      ⚠ deux annonces actives sur {row.duplicate_platform_warning.join(", ")}
                    </p>
                  )}
                </td>
                <td className="p-3">
                  <span className="text-xs">{STATUS_LABELS[row.status] ?? row.status}</span>
                  {row.is_stale && (
                    <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">
                      dormant
                    </span>
                  )}
                </td>
                <td className="p-3 text-xs">{euros(row.purchase_cost_cents)}</td>
                <td className="p-3 text-xs">{euros(row.best_price_cents)}</td>
                <td className="p-3 text-xs">
                  {euros(row.expected_margin_cents)}
                  {row.expected_margin_pct !== null && (
                    <span className="text-muted"> ({row.expected_margin_pct} %)</span>
                  )}
                </td>
                <td className="p-3">
                  {row.publications.length === 0 ? (
                    <span className="text-xs text-muted">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {row.publications.map((cell) => (
                        <span
                          key={cell.publication_id}
                          className="rounded border border-line px-1.5 py-0.5 text-[10px]"
                          title={`${cell.account_label} · ${cell.status}`}
                        >
                          {cell.platform} · {cell.status}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="p-4 text-sm text-muted">Aucun article ne correspond.</p>
        )}
      </div>
    </main>
  );
}
