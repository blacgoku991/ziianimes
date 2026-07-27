"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearTokens } from "@/lib/api";
import type { Session } from "@/lib/types";

export function Header({ session }: { session: Session | null }) {
  const router = useRouter();

  return (
    <header className="mb-8 flex items-center justify-between border-b border-line pb-4">
      <div>
        <Link href="/articles" className="text-lg font-semibold">
          Ziia
        </Link>
        <p className="text-xs text-muted">
          Étape 1 — préparation. Aucune publication automatique.
        </p>
      </div>
      {session && (
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted">{session.workspace.name}</span>
          <button
            className="btn-ghost"
            onClick={() => {
              clearTokens();
              router.push("/login");
            }}
          >
            Déconnexion
          </button>
        </div>
      )}
    </header>
  );
}
