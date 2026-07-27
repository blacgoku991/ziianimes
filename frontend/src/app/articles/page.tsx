"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Header } from "@/components/Header";
import { api } from "@/lib/api";
import type { Article, Session } from "@/lib/types";

export default function ArticlesPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [search, setSearch] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (term = "") => {
      try {
        const list = await api.listArticles(term);
        setArticles(list.items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Chargement impossible");
      }
    },
    [],
  );

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
    try {
      const article = await api.createArticle({ title: title || null });
      router.push(`/articles/${article.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Création impossible");
    }
  }

  if (loading) return <p className="text-sm text-muted">Chargement…</p>;

  return (
    <main>
      <Header session={session} />

      <div className="mb-6 grid gap-4 md:grid-cols-[2fr_1fr]">
        <form onSubmit={onCreate} className="card flex gap-2">
          <input
            className="field"
            placeholder="Nouvel article — ex. Sweat Nike gris"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <button className="btn-primary shrink-0" type="submit">
            Créer
          </button>
        </form>

        <form
          className="card flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void load(search);
          }}
        >
          <input
            className="field"
            placeholder="Rechercher (titre, marque, réf.)"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className="btn-ghost shrink-0" type="submit">
            Filtrer
          </button>
        </form>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {articles.length === 0 ? (
        <p className="card text-sm text-muted">
          Aucun article. Créez-en un, puis ajoutez ses photos.
        </p>
      ) : (
        <ul className="grid gap-3">
          {articles.map((article) => (
            <li key={article.id}>
              <Link
                href={`/articles/${article.id}`}
                className="card flex items-center justify-between hover:border-neutral-300"
              >
                <div>
                  <p className="font-medium">
                    {article.title ?? "Sans titre"}{" "}
                    <span className="text-xs text-muted">{article.sku}</span>
                  </p>
                  <p className="text-xs text-muted">
                    {article.brand ?? "marque non renseignée"} ·{" "}
                    {article.status}
                  </p>
                </div>
                <span className="text-xs text-muted">
                  coût {(article.purchase_cost_cents / 100).toFixed(2)} €
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
