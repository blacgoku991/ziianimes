"use client";

import { ChangeEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Nav, euros } from "@/components/Nav";
import { PhotoPanel } from "@/components/PhotoPanel";
import { api } from "@/lib/api";
import type {
  Account,
  ArticleDetail,
  PriceAdvice,
  Publication,
  Session,
} from "@/lib/types";

export default function ArticlePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [price, setPrice] = useState<PriceAdvice | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      try {
        setSession(await api.me());
        setArticle(await api.getArticle(params.id));
        setAccounts(await api.listAccounts());
        setPublications(await api.listPublications(params.id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Article introuvable");
      }
    })();
  }, [params.id]);

  async function onUpload(event: ChangeEvent<HTMLInputElement>) {
    if (!event.target.files?.length || !article) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadPhotos(article.id, event.target.files);
      setArticle(await api.getArticle(article.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Envoi impossible");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  async function saveField(field: string, value: string) {
    if (!article) return;
    const updated = await api.updateArticle(article.id, { [field]: value });
    setArticle({ ...article, ...updated });
  }

  async function runStep(key: string, action: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await action();
      if (article) {
        setArticle(await api.getArticle(article.id));
        setPublications(await api.listPublications(article.id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action impossible");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!article) return <p className="text-sm text-muted">Chargement…</p>;

  return (
    <main>
      <Nav session={session} />

      <div className="mb-4 flex items-center justify-between">
        <Link href="/articles" className="text-sm text-muted underline">
          ← Tous les articles
        </Link>
        <button
          className="btn-ghost text-xs text-red-600"
          onClick={async () => {
            await api.deleteArticle(article.id);
            router.push("/articles");
          }}
        >
          Supprimer l&apos;article
        </button>
      </div>

      <section className="card mb-6">
        <p className="mb-3 text-xs uppercase tracking-wide text-muted">
          Réf. {article.sku}
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <label className="label">Titre</label>
            <input
              className="field"
              defaultValue={article.title ?? ""}
              onBlur={(e) => void saveField("title", e.target.value)}
            />
          </div>
          <div>
            <label className="label">Marque</label>
            <input
              className="field"
              defaultValue={article.brand ?? ""}
              onBlur={(e) => void saveField("brand", e.target.value)}
            />
          </div>
          <div>
            <label className="label">Taille</label>
            <input
              className="field"
              defaultValue={article.size_label ?? ""}
              onBlur={(e) => void saveField("size_label", e.target.value)}
            />
          </div>
        </div>
      </section>

      <section className="card mb-6">
        <p className="label mb-2">Préparation assistée</p>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-ghost text-xs"
            disabled={busy !== null}
            onClick={() => runStep("analyse", () => api.analyseArticle(article.id))}
          >
            {busy === "analyse" ? "Analyse…" : "Analyser les photos"}
          </button>
          <button
            className="btn-ghost text-xs"
            disabled={busy !== null}
            onClick={() => runStep("copy", () => api.generateCopy(article.id, 3))}
          >
            {busy === "copy" ? "Rédaction…" : "Rédiger les annonces"}
          </button>
          <button
            className="btn-ghost text-xs"
            disabled={busy !== null}
            onClick={() =>
              runStep("price", async () => setPrice(await api.suggestPrice(article.id)))
            }
          >
            {busy === "price" ? "Calcul…" : "Prix conseillé"}
          </button>
        </div>

        {price && (
          <div className="mt-3 rounded-md border border-line p-3 text-xs">
            <p>
              Fourchette : {euros(price.low_cents)} — {euros(price.median_cents)} —{" "}
              {euros(price.high_cents)} · conseillé{" "}
              <strong>{euros(price.recommended_cents)}</strong>
            </p>
            <p className="mt-1 text-muted">
              base : {price.basis} · {price.sample_size} comparable(s)
              {price.reliable ? "" : " · échantillon non fiable"}
            </p>
            {price.margin && (
              <p className="mt-1 text-muted">
                marge nette estimée : {euros(price.margin.margin_cents)} (
                {price.margin.margin_pct} %), frais {euros(price.margin.fee_cents)}
              </p>
            )}
            {price.warnings.map((warning) => (
              <p key={warning} className="mt-1 text-amber-700">
                {warning}
              </p>
            ))}
          </div>
        )}
      </section>

      <section className="card mb-6">
        <p className="label mb-2">Publier</p>
        {accounts.length === 0 ? (
          <p className="text-sm text-muted">
            Aucun compte rattaché. Rendez-vous dans « Comptes ».
          </p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              {accounts.map((account) => (
                <label
                  key={account.id}
                  className="flex items-center gap-2 rounded-md border border-line px-2 py-1 text-xs"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(account.id)}
                    onChange={(e) =>
                      setSelected((current) =>
                        e.target.checked
                          ? [...current, account.id]
                          : current.filter((id) => id !== account.id),
                      )
                    }
                  />
                  {account.label}
                  <span className="text-muted">{account.platform}</span>
                </label>
              ))}
            </div>
            <button
              className="btn-primary text-xs"
              disabled={busy !== null || selected.length === 0}
              onClick={() =>
                runStep("publish", () =>
                  api.preparePublications(article.id, selected, "draft", true),
                )
              }
            >
              {busy === "publish" ? "Préparation…" : "Préparer en brouillon"}
            </button>
            <p className="mt-2 text-[11px] text-muted">
              La publication passe par une file d&apos;attente : une à la fois
              par compte, avec des délais entre les actions. Le statut
              ci-dessous suit l&apos;avancement.
            </p>
          </>
        )}

        {publications.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs">
            {publications.map((publication) => (
              <li key={publication.id} className="flex justify-between border-b border-line py-1">
                <span>
                  {publication.title ?? "—"}{" "}
                  <span className="text-muted">({publication.mode})</span>
                </span>
                <span className="text-muted">
                  {publication.status} · {euros(publication.price_cents)}
                  {publication.last_error ? ` · ${publication.last_error}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card mb-6">
        <label className="label" htmlFor="photos">
          Ajouter des photos (JPEG, PNG ou WebP, pleine résolution)
        </label>
        <input
          id="photos"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={onUpload}
          disabled={uploading}
          className="text-sm"
        />
        <p className="mt-2 text-xs text-muted">
          Le fichier d&apos;origine est conservé tel quel : c&apos;est lui qui
          sert de base à toutes les variantes.
        </p>
      </section>

      <div className="space-y-4">
        {article.photos.length === 0 ? (
          <p className="card text-sm text-muted">
            Aucune photo pour l&apos;instant.
          </p>
        ) : (
          article.photos.map((photo) => (
            <PhotoPanel
              key={photo.id}
              photo={photo}
              onDeleted={(photoId) =>
                setArticle({
                  ...article,
                  photos: article.photos.filter((item) => item.id !== photoId),
                })
              }
            />
          ))
        )}
      </div>
    </main>
  );
}
