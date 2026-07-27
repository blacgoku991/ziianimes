"use client";

import { useState } from "react";
import { api, mediaUrl } from "@/lib/api";
import type { Variant } from "@/lib/types";

/**
 * Affiche une variante et sa mesure d'écart.
 *
 * La distance pHash est montrée telle quelle plutôt que masquée derrière un
 * indicateur binaire : c'est l'information qui permet à l'utilisateur de
 * décider s'il régénère ou s'il publie.
 */
export function VariantCard({
  variant,
  onChanged,
}: {
  variant: Variant;
  onChanged: (variant: Variant) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<Variant>) {
    setBusy(true);
    try {
      onChanged(await action());
    } finally {
      setBusy(false);
    }
  }

  const distance = variant.phash_distance_to_source;
  const distanceTone =
    distance === null
      ? "text-muted"
      : distance >= 10
        ? "text-emerald-700"
        : "text-amber-700";

  return (
    <figure className="rounded-md border border-line bg-white p-2">
      <div className="relative aspect-[3/4] overflow-hidden rounded bg-neutral-100">
        {variant.status === "pending" ? (
          <div className="flex h-full items-center justify-center text-xs text-muted">
            Rendu en cours…
          </div>
        ) : variant.status === "failed" ? (
          <div className="flex h-full items-center justify-center p-3 text-center text-xs text-red-600">
            {variant.failure_reason ?? "Échec du rendu"}
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(variant.url)}
            alt={`Variante ${variant.variant_index + 1}`}
            className="h-full w-full object-cover"
          />
        )}
        {variant.status === "accepted" && (
          <span className="absolute left-1 top-1 rounded bg-emerald-600 px-1.5 py-0.5 text-[10px] font-medium text-white">
            retenue
          </span>
        )}
        {variant.status === "rejected" && (
          <span className="absolute left-1 top-1 rounded bg-neutral-500 px-1.5 py-0.5 text-[10px] font-medium text-white">
            écartée
          </span>
        )}
      </div>

      <figcaption className="mt-2 space-y-1 text-[11px] leading-tight text-muted">
        <p>
          Variante {variant.variant_index + 1} ·{" "}
          {variant.width && variant.height
            ? `${variant.width}×${variant.height}`
            : "—"}
        </p>
        <p className={distanceTone}>
          écart avec l&apos;originale : {distance ?? "—"}/64
        </p>
        <p>
          fond{" "}
          {variant.background_replaced ? "remplacé" : "d'origine conservé"}
        </p>
      </figcaption>

      <div className="mt-2 flex gap-1">
        <button
          className="btn-ghost flex-1 px-2 py-1 text-xs"
          disabled={busy}
          onClick={() => run(() => api.regenerateVariant(variant.id))}
        >
          Régénérer
        </button>
        <button
          className="btn-ghost px-2 py-1 text-xs"
          disabled={busy || variant.status === "pending"}
          onClick={() => run(() => api.decideVariant(variant.id, true))}
          title="Retenir cette variante"
        >
          ✓
        </button>
        <button
          className="btn-ghost px-2 py-1 text-xs"
          disabled={busy || variant.status === "pending"}
          onClick={() => run(() => api.decideVariant(variant.id, false))}
          title="Écarter cette variante"
        >
          ✕
        </button>
      </div>
    </figure>
  );
}
