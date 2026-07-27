export type ArticleStatus = "draft" | "listed" | "reserved" | "sold" | "withdrawn";

export type VariantStatus = "pending" | "ready" | "failed" | "accepted" | "rejected";

export interface Variant {
  id: string;
  source_photo_id: string;
  variant_index: number;
  status: VariantStatus;
  width: number | null;
  height: number | null;
  byte_size: number | null;
  phash: string | null;
  /** Distance de Hamming avec la source : 0 = identique, 64 = tout diffère. */
  phash_distance_to_source: number | null;
  background_replaced: boolean;
  recipe: Record<string, unknown>;
  failure_reason: string | null;
  render_count: number;
  render_ms: number | null;
  rendered_at: string | null;
  url: string | null;
}

export interface Photo {
  id: string;
  article_id: string;
  position: number;
  content_type: string;
  byte_size: number;
  width: number;
  height: number;
  status: string;
  original_filename: string | null;
  created_at: string;
  url: string | null;
  variants: Variant[];
}

export interface Article {
  id: string;
  sku: string;
  title: string | null;
  description: string | null;
  brand: string | null;
  category_label: string | null;
  size_label: string | null;
  color: string | null;
  material: string | null;
  condition: string | null;
  status: ArticleStatus;
  quantity: number;
  purchase_cost_cents: number;
  target_margin_pct: number | null;
  floor_price_cents: number | null;
  currency: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArticleDetail extends Article {
  photos: Photo[];
}

export interface ArticleList {
  items: Article[];
  total: number;
  limit: number;
  offset: number;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  plan: string;
  subscription_status: string;
  trial_ends_at: string | null;
  automation_notice_accepted_at: string | null;
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  created_at: string;
}

export interface Session {
  user: User;
  workspace: Workspace;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// -- Étape 2 : intelligence ---------------------------------------------------

export interface Analysis {
  garment_type: string | null;
  brand: string | null;
  brand_confidence: number;
  color: string | null;
  material: string | null;
  fit: string | null;
  size_label: string | null;
  condition: string | null;
  defects: string[];
  /** Un logo visible coupe le miroir horizontal, qui l'inverserait. */
  has_visible_logo_or_text: boolean;
  keywords: string[];
}

export interface CopyVariant {
  title: string;
  description: string;
  keywords: string[];
}

export interface MatchCandidate {
  external_id: string;
  label: string;
  path: string;
  score: number;
  source: string;
}

export interface MatchResult {
  best: MatchCandidate | null;
  candidates: MatchCandidate[];
  /** Vrai quand il faut poser la question plutôt que publier une supposition. */
  needs_user_choice: boolean;
}

export interface PriceAdvice {
  low_cents: number;
  median_cents: number;
  high_cents: number;
  recommended_cents: number;
  floor_cents: number;
  sample_size: number;
  reliable: boolean;
  /** `ventes_propres` | `prix_demandes` | `cout_et_marge` — affiché tel quel. */
  basis: string;
  comparables: { price_cents: number; source: string; label: string }[];
  margin: {
    fee_cents: number;
    net_proceeds_cents: number;
    margin_cents: number;
    margin_pct: number;
  } | null;
  warnings: string[];
}

// -- Étape 3 : stock ----------------------------------------------------------

export interface PublicationCell {
  publication_id: string;
  account_id: string;
  account_label: string;
  platform: string;
  status: string;
  price_cents: number | null;
  remote_url: string | null;
  days_online: number | null;
  views_count: number;
}

export interface StockRow {
  id: string;
  sku: string;
  title: string | null;
  brand: string | null;
  category_label: string | null;
  size_label: string | null;
  status: string;
  purchase_cost_cents: number;
  photo_count: number;
  best_price_cents: number | null;
  expected_margin_cents: number | null;
  expected_margin_pct: number | null;
  days_since_listed: number | null;
  is_stale: boolean;
  duplicate_platform_warning: string[];
  publications: PublicationCell[];
}

export interface StockSummary {
  by_status: Record<string, number>;
  total: number;
  capital_immobilise_cents: number;
}

export interface StaleSuggestion {
  article_id: string;
  sku: string;
  title: string | null;
  days_online: number;
  current_price_cents: number;
  suggested_price_cents: number;
  floor_cents: number;
  reason: string;
}

// -- Étape 4 : comptes --------------------------------------------------------

export interface Account {
  id: string;
  platform: string;
  label: string;
  niche: string | null;
  external_username: string | null;
  auth_type: string;
  status: string;
  last_error: string | null;
  daily_action_count: number;
}

export interface AccountHealth {
  id: string;
  platform: string;
  label: string;
  niche: string | null;
  status: string;
  has_credentials: boolean;
  last_health_check_at: string | null;
  health_check_overdue: boolean;
  last_error: string | null;
  daily_action_count: number;
  daily_action_cap: number;
}

// -- Étape 5 : publications ---------------------------------------------------

export interface Publication {
  id: string;
  article_id: string;
  marketplace_account_id: string;
  mode: "draft" | "autopublish";
  status: string;
  title: string | null;
  price_cents: number | null;
  currency: string;
  remote_url: string | null;
  published_at: string | null;
  sold_at: string | null;
  sale_price_cents: number | null;
  net_proceeds_cents: number | null;
  views_count: number;
  attempts: number;
  last_error: string | null;
}

export interface PublicationEvent {
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface SaleOutcome {
  publication_id: string;
  unpublished_publication_ids: string[];
  /** Deux acheteurs pour une pièce unique : conflit à réconcilier. */
  oversold: boolean;
  margin: Record<string, number> | null;
}

// -- Étape 6 : boîte de réception et tableau de bord ---------------------------

export interface Thread {
  id: string;
  account_label: string;
  platform: string;
  counterparty_name: string | null;
  unread_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
  best_offer_cents: number | null;
}

export interface ThreadMessage {
  id: string;
  direction: "inbound" | "outbound";
  body: string;
  offer_price_cents: number | null;
  created_at: string;
}

export interface QuickReply {
  id: string;
  label: string;
  body: string;
  usage_count: number;
}

export interface Dashboard {
  overview: {
    period_days: number;
    sold_count: number;
    revenue_cents: number;
    net_proceeds_cents: number;
    purchase_cost_cents: number;
    margin_cents: number;
    margin_pct: number;
    average_sale_cents: number;
    average_days_to_sale: number | null;
    live_publications: number;
    articles_in_stock: number;
    capital_immobilise_cents: number;
    ai_cost_micros: number;
  };
  by_account: {
    account_id: string;
    label: string;
    niche: string | null;
    platform: string;
    sold_count: number;
    net_proceeds_cents: number;
    margin_cents: number;
    margin_pct: number;
    average_days_to_sale: number | null;
  }[];
  top_brands: { brand: string; sold_count: number; margin_cents: number }[];
  top_categories: { category: string; sold_count: number; margin_cents: number }[];
  timeline: { date: string; sold_count: number; net_proceeds_cents: number }[];
  /** Fenêtre de survente : deux acheteurs peuvent acheter entre deux passages. */
  sync_interval_seconds: number;
}
