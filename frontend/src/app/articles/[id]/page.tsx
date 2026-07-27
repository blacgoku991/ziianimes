"use client";

import { ChangeEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Header } from "@/components/Header";
import { PhotoPanel } from "@/components/PhotoPanel";
import { api } from "@/lib/api";
import type { ArticleDetail, Session } from "@/lib/types";

export default function ArticlePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setSession(await api.me());
        setArticle(await api.getArticle(params.id));
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

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!article) return <p className="text-sm text-muted">Chargement…</p>;

  return (
    <main>
      <Header session={session} />

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
