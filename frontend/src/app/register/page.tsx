"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.register({
        email,
        password,
        workspace_name: workspaceName || undefined,
      });
      router.push("/articles");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Inscription impossible");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm">
      <h1 className="mb-6 text-xl font-semibold">Créer un espace de travail</h1>
      <form onSubmit={onSubmit} className="card space-y-4">
        <div>
          <label className="label" htmlFor="workspace">
            Nom de l&apos;espace
          </label>
          <input
            id="workspace"
            className="field"
            value={workspaceName}
            onChange={(e) => setWorkspaceName(e.target.value)}
            placeholder="Friperie Camille"
          />
        </div>
        <div>
          <label className="label" htmlFor="email">
            Adresse e-mail
          </label>
          <input
            id="email"
            type="email"
            className="field"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="label" htmlFor="password">
            Mot de passe
          </label>
          <input
            id="password"
            type="password"
            className="field"
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <p className="mt-1 text-xs text-muted">10 caractères minimum.</p>
        </div>

        <div className="rounded-md bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
          <strong>À lire avant de commencer.</strong> L&apos;automatisation des
          publications est contraire aux conditions d&apos;utilisation de
          certaines plateformes. Le risque de restriction de compte est porté
          par l&apos;utilisateur. Le mode brouillon, où vous donnez vous-même le
          dernier clic, reste disponible en permanence et constitue le
          comportement par défaut.
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "Création…" : "Créer mon espace"}
        </button>
      </form>
      <p className="mt-4 text-sm text-muted">
        Déjà inscrit ?{" "}
        <Link href="/login" className="underline">
          Se connecter
        </Link>
      </p>
    </main>
  );
}
