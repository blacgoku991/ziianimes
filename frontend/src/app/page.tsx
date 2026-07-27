"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace(getAccessToken() ? "/articles" : "/login");
  }, [router]);

  return <p className="text-sm text-muted">Chargement…</p>;
}
