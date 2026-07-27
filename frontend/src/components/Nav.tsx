"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearTokens } from "@/lib/api";
import type { Session } from "@/lib/types";

const LINKS = [
  { href: "/articles", label: "Articles" },
  { href: "/stock", label: "Stock" },
  { href: "/comptes", label: "Comptes" },
  { href: "/inbox", label: "Messages" },
  { href: "/tableau-de-bord", label: "Tableau de bord" },
];

export function Nav({ session }: { session: Session | null }) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <header className="mb-8 border-b border-line pb-3">
      <div className="flex items-center justify-between">
        <Link href="/articles" className="text-lg font-semibold">
          Ziia
        </Link>
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
      </div>
      <nav className="mt-3 flex gap-1 text-sm">
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`rounded-md px-3 py-1.5 ${
              pathname.startsWith(link.href)
                ? "bg-ink text-white"
                : "text-muted hover:bg-neutral-100"
            }`}
          >
            {link.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}

export function euros(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "—";
  return `${(cents / 100).toFixed(2)} €`;
}
