"use client";

import type {
  Article,
  ArticleDetail,
  ArticleList,
  Photo,
  Session,
  Tokens,
  Variant,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_KEY = "ziia.access_token";
const REFRESH_KEY = "ziia.refresh_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function storeTokens(tokens: Tokens): void {
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

/** Les URL média renvoyées par l'API sont relatives et déjà signées. */
export function mediaUrl(path: string | null): string | undefined {
  return path ? `${API_URL}${path}` : undefined;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retryOnExpiry = true,
): Promise<T> {
  const token = getAccessToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (response.status === 401 && retryOnExpiry && (await refreshSession())) {
    return request<T>(path, options, false);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.error ?? body?.detail;
    const message =
      (typeof detail === "string" ? detail : detail?.message) ??
      `Erreur ${response.status}`;
    throw new ApiError(message, response.status, body?.error?.code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Rejoue une session expirée avec le jeton de rafraîchissement. */
async function refreshSession(): Promise<boolean> {
  const refreshToken =
    typeof window === "undefined"
      ? null
      : window.localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return false;

  const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    clearTokens();
    return false;
  }
  storeTokens((await response.json()) as Tokens);
  return true;
}

export const api = {
  async register(payload: {
    email: string;
    password: string;
    workspace_name?: string;
  }): Promise<Session> {
    const body = await request<{
      user: Session["user"];
      workspace: Session["workspace"];
      tokens: Tokens;
    }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    storeTokens(body.tokens);
    return { user: body.user, workspace: body.workspace };
  },

  async login(email: string, password: string): Promise<Tokens> {
    const tokens = await request<Tokens>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    storeTokens(tokens);
    return tokens;
  },

  me: () => request<Session>("/api/v1/auth/me"),

  listArticles: (search = "") =>
    request<ArticleList>(
      `/api/v1/articles${search ? `?search=${encodeURIComponent(search)}` : ""}`,
    ),

  createArticle: (payload: Partial<Article>) =>
    request<ArticleDetail>("/api/v1/articles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getArticle: (id: string) => request<ArticleDetail>(`/api/v1/articles/${id}`),

  updateArticle: (id: string, payload: Partial<Article>) =>
    request<Article>(`/api/v1/articles/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteArticle: (id: string) =>
    request<void>(`/api/v1/articles/${id}`, { method: "DELETE" }),

  uploadPhotos: (articleId: string, files: FileList | File[]) => {
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    return request<Photo[]>(`/api/v1/articles/${articleId}/photos`, {
      method: "POST",
      body: form,
    });
  },

  deletePhoto: (photoId: string) =>
    request<void>(`/api/v1/photos/${photoId}`, { method: "DELETE" }),

  generateVariants: (photoId: string, count: number, synchronous = false) =>
    request<{ variants: Variant[]; queued: boolean }>(
      `/api/v1/photos/${photoId}/variants`,
      {
        method: "POST",
        body: JSON.stringify({ count, synchronous }),
      },
    ),

  listPhotoVariants: (photoId: string) =>
    request<Variant[]>(`/api/v1/photos/${photoId}/variants`),

  regenerateVariant: (variantId: string) =>
    request<Variant>(`/api/v1/variants/${variantId}/regenerate`, {
      method: "POST",
    }),

  decideVariant: (variantId: string, accepted: boolean) =>
    request<Variant>(`/api/v1/variants/${variantId}/decision`, {
      method: "POST",
      body: JSON.stringify({ accepted }),
    }),
};
