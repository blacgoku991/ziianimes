"use client";

import { useEffect, useRef, useState } from "react";
import { api, mediaUrl } from "@/lib/api";
import type { Photo, Variant } from "@/lib/types";
import { VariantCard } from "./VariantCard";

/**
 * Panneau avant/après d'une photo : la source à gauche, les variantes à
 * droite.
 *
 * Le rendu étant mis en file, les variantes reviennent d'abord à l'état
 * « en cours ». On interroge l'API jusqu'à ce qu'elles soient toutes
 * rendues, plutôt que de laisser croire à un résultat instantané.
 */
export function PhotoPanel({
  photo,
  onDeleted,
}: {
  photo: Photo;
  onDeleted: (photoId: string) => void;
}) {
  const [variants, setVariants] = useState<Variant[]>(photo.variants);
  const [count, setCount] = useState(3);
  const [busy, setBusy] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  function schedulePoll(current: Variant[]) {
    if (!current.some((variant) => variant.status === "pending")) return;
    pollTimer.current = setTimeout(async () => {
      const fresh = await api.listPhotoVariants(photo.id);
      setVariants(fresh);
      schedulePoll(fresh);
    }, 1500);
  }

  async function generate() {
    setBusy(true);
    try {
      const result = await api.generateVariants(photo.id, count);
      setVariants(result.variants);
      schedulePoll(result.variants);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    await api.deletePhoto(photo.id);
    onDeleted(photo.id);
  }

  return (
    <section className="card">
      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        <div>
          <p className="label">Source — pleine résolution</p>
          <div className="aspect-[3/4] overflow-hidden rounded bg-neutral-100">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={mediaUrl(photo.url)}
              alt={photo.original_filename ?? "Photo source"}
              className="h-full w-full object-cover"
            />
          </div>
          <p className="mt-2 text-[11px] text-muted">
            {photo.width}×{photo.height} · {Math.round(photo.byte_size / 1024)} Ko
          </p>
          <div className="mt-2 flex items-center gap-2">
            <select
              className="field py-1 text-xs"
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6].map((value) => (
                <option key={value} value={value}>
                  {value} variante{value > 1 ? "s" : ""}
                </option>
              ))}
            </select>
            <button
              className="btn-primary shrink-0 px-2 py-1 text-xs"
              onClick={generate}
              disabled={busy}
            >
              {busy ? "…" : "Générer"}
            </button>
          </div>
          <button
            className="btn-ghost mt-2 w-full px-2 py-1 text-xs text-red-600"
            onClick={remove}
          >
            Supprimer la photo
          </button>
        </div>

        <div>
          <p className="label">Variantes</p>
          {variants.length === 0 ? (
            <p className="text-sm text-muted">
              Aucune variante générée pour cette photo.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              {variants.map((variant) => (
                <VariantCard
                  key={variant.id}
                  variant={variant}
                  onChanged={(updated) =>
                    setVariants((current) =>
                      current.map((item) =>
                        item.id === updated.id ? updated : item,
                      ),
                    )
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
