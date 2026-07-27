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
