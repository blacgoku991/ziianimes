"use client";

import type {
  Account,
  AccountHealth,
  Analysis,
  Article,
  ArticleDetail,
  ArticleList,
  CopyVariant,
  Dashboard,
  MatchResult,
  Photo,
  PriceAdvice,
  Publication,
  PublicationEvent,
  QuickReply,
  SaleOutcome,
  Session,
  StaleSuggestion,
  StockRow,
  StockSummary,
  Thread,
  ThreadMessage,
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

  // -- Étape 2 : intelligence ------------------------------------------------

  analyseArticle: (articleId: string, hint?: string) =>
    request<Analysis>(`/api/v1/articles/${articleId}/analyse`, {
      method: "POST",
      body: JSON.stringify({ hint: hint ?? null }),
    }),

  generateCopy: (articleId: string, variantCount = 3, niche?: string) =>
    request<{ variants: CopyVariant[] }>(`/api/v1/articles/${articleId}/copy`, {
      method: "POST",
      body: JSON.stringify({ variant_count: variantCount, niche: niche ?? null }),
    }),

  suggestPrice: (articleId: string, platform = "vinted") =>
    request<PriceAdvice>(`/api/v1/articles/${articleId}/price`, {
      method: "POST",
      body: JSON.stringify({ platform }),
    }),

  importReferentials: () =>
    request<Record<string, Record<string, number>>>("/api/v1/referentials/import", {
      method: "POST",
    }),

  searchCategories: (q: string) =>
    request<{ external_id: string; name: string; path: string }[]>(
      `/api/v1/referentials/categories?q=${encodeURIComponent(q)}`,
    ),

  matchCategory: (label: string, context?: string) =>
    request<MatchResult>("/api/v1/mapping/category", {
      method: "POST",
      body: JSON.stringify({ label, context: context ?? null }),
    }),

  rememberCategory: (label: string, externalId: string) =>
    request<MatchResult>("/api/v1/mapping/category/remember", {
      method: "POST",
      body: JSON.stringify({ label, external_id: externalId }),
    }),

  // -- Étape 3 : stock -------------------------------------------------------

  stock: (params: Record<string, string> = {}) => {
    const query = new URLSearchParams(params).toString();
    return request<{ items: StockRow[]; total: number; summary: StockSummary }>(
      `/api/v1/stock${query ? `?${query}` : ""}`,
    );
  },

  staleListings: () => request<StaleSuggestion[]>("/api/v1/stock/stale"),

  // -- Étape 4 : comptes -----------------------------------------------------

  listAccounts: () => request<Account[]>("/api/v1/accounts"),

  accountsHealth: () => request<AccountHealth[]>("/api/v1/accounts/health"),

  createAccount: (payload: {
    platform: string;
    label: string;
    niche?: string | null;
  }) =>
    request<Account>("/api/v1/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  storeCredentials: (accountId: string, payload: Record<string, unknown>) =>
    request<Account>(`/api/v1/accounts/${accountId}/credentials`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteAccount: (accountId: string) =>
    request<void>(`/api/v1/accounts/${accountId}`, { method: "DELETE" }),

  acceptAutomationNotice: (accepted: boolean) =>
    request<{ accepted: boolean; accepted_at: string | null }>(
      "/api/v1/workspace/automation-notice",
      { method: "POST", body: JSON.stringify({ accepted }) },
    ),

  // -- Étape 5 : publications ------------------------------------------------

  preparePublications: (
    articleId: string,
    accountIds: string[],
    mode: "draft" | "autopublish" = "draft",
    enqueue = false,
  ) =>
    request<Publication[]>(`/api/v1/articles/${articleId}/publications`, {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds, mode, enqueue }),
    }),

  listPublications: (articleId?: string) =>
    request<Publication[]>(
      `/api/v1/publications${articleId ? `?article_id=${articleId}` : ""}`,
    ),

  enqueuePublication: (publicationId: string) =>
    request<Publication>(`/api/v1/publications/${publicationId}/enqueue`, {
      method: "POST",
    }),

  markSold: (publicationId: string, salePriceCents?: number) =>
    request<SaleOutcome>(`/api/v1/publications/${publicationId}/sold`, {
      method: "POST",
      body: JSON.stringify({ sale_price_cents: salePriceCents ?? null }),
    }),

  publicationEvents: (publicationId: string) =>
    request<PublicationEvent[]>(`/api/v1/publications/${publicationId}/events`),

  // -- Étape 6 : boîte de réception et tableau de bord ------------------------

  inbox: (unreadOnly = false) =>
    request<Thread[]>(`/api/v1/inbox${unreadOnly ? "?unread_only=true" : ""}`),

  threadMessages: (threadId: string) =>
    request<ThreadMessage[]>(`/api/v1/inbox/${threadId}`),

  reply: (threadId: string, body: string) =>
    request<{ id: string; queued: boolean }>(`/api/v1/inbox/${threadId}/reply`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),

  quickReplies: () => request<QuickReply[]>("/api/v1/quick-replies"),

  dashboard: (days = 30) => request<Dashboard>(`/api/v1/dashboard?days=${days}`),
};
