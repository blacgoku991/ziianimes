"""Schéma initial : identité, catalogue, comptes marketplace, publications,
référentiels plateformes et messagerie.

Toutes les tables sont posées en une seule révision : la forme du modèle
« un article, N publications » et les invariants d'isolation multi-locataire
sont structurants, mieux vaut les figer avant d'écrire la première ligne de
connecteur.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('platform_brands',
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('external_id', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('normalized_name', sa.String(length=200), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_brands')),
    sa.UniqueConstraint('platform', 'external_id', name='uq_platform_brands_platform_ext')
    )
    op.create_index('ix_platform_brands_platform_normalized', 'platform_brands', ['platform', 'normalized_name'], unique=False)
    op.create_table('platform_categories',
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('external_id', sa.String(length=120), nullable=False),
    sa.Column('parent_external_id', sa.String(length=120), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('path', sa.String(length=600), nullable=False),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('is_leaf', sa.Boolean(), nullable=False),
    sa.Column('size_group_external_id', sa.String(length=120), nullable=True),
    sa.Column('raw', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_categories')),
    sa.UniqueConstraint('platform', 'external_id', name='uq_platform_categories_platform_ext')
    )
    op.create_index(op.f('ix_platform_categories_parent_external_id'), 'platform_categories', ['parent_external_id'], unique=False)
    op.create_index('ix_platform_categories_platform_leaf', 'platform_categories', ['platform', 'is_leaf'], unique=False)
    op.create_table('platform_sizes',
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('external_id', sa.String(length=120), nullable=False),
    sa.Column('size_group_external_id', sa.String(length=120), nullable=True),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('normalized_name', sa.String(length=80), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_sizes')),
    sa.UniqueConstraint('platform', 'external_id', name='uq_platform_sizes_platform_ext')
    )
    op.create_index('ix_platform_sizes_platform_group', 'platform_sizes', ['platform', 'size_group_external_id'], unique=False)
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('workspaces',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('slug', sa.String(length=140), nullable=False),
    sa.Column('plan', sa.String(length=40), nullable=False),
    sa.Column('subscription_status', sa.Enum('trialing', 'active', 'past_due', 'canceled', 'incomplete', name='subscriptionstatus', native_enum=False, length=32), nullable=False),
    sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stripe_customer_id', sa.String(length=80), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=80), nullable=True),
    sa.Column('automation_notice_accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('settings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces')),
    sa.UniqueConstraint('slug', name=op.f('uq_workspaces_slug')),
    sa.UniqueConstraint('stripe_customer_id', name=op.f('uq_workspaces_stripe_customer_id')),
    sa.UniqueConstraint('stripe_subscription_id', name=op.f('uq_workspaces_stripe_subscription_id'))
    )
    op.create_table('articles',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('sku', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('brand', sa.String(length=120), nullable=True),
    sa.Column('category_label', sa.String(length=200), nullable=True),
    sa.Column('size_label', sa.String(length=40), nullable=True),
    sa.Column('color', sa.String(length=60), nullable=True),
    sa.Column('material', sa.String(length=120), nullable=True),
    sa.Column('condition', sa.Enum('new_with_tags', 'new_without_tags', 'very_good', 'good', 'fair', name='articlecondition', native_enum=False, length=32), nullable=True),
    sa.Column('attributes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.Enum('draft', 'listed', 'reserved', 'sold', 'withdrawn', name='articlestatus', native_enum=False, length=32), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('purchase_cost_cents', sa.Integer(), nullable=False),
    sa.Column('target_margin_pct', sa.Float(), nullable=True),
    sa.Column('floor_price_cents', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('first_listed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sold_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('purchase_cost_cents >= 0', name=op.f('ck_articles_purchase_cost_positive')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_articles_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_articles')),
    sa.UniqueConstraint('workspace_id', 'sku', name='uq_articles_workspace_id_sku')
    )
    op.create_index(op.f('ix_articles_brand'), 'articles', ['brand'], unique=False)
    op.create_index(op.f('ix_articles_deleted_at'), 'articles', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_articles_status'), 'articles', ['status'], unique=False)
    op.create_index(op.f('ix_articles_workspace_id'), 'articles', ['workspace_id'], unique=False)
    op.create_index('ix_articles_workspace_status', 'articles', ['workspace_id', 'status'], unique=False)
    op.create_table('brand_mappings',
    sa.Column('workspace_id', sa.Uuid(), nullable=True),
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('source_key', sa.String(length=200), nullable=False),
    sa.Column('brand_external_id', sa.String(length=120), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('source', sa.Enum('manual', 'embedding', 'llm', 'imported', name='mappingsource', native_enum=False, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_brand_mappings_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brand_mappings')),
    sa.UniqueConstraint('workspace_id', 'platform', 'source_key', name='uq_brand_mappings_workspace_key')
    )
    op.create_index(op.f('ix_brand_mappings_workspace_id'), 'brand_mappings', ['workspace_id'], unique=False)
    op.create_table('category_mappings',
    sa.Column('workspace_id', sa.Uuid(), nullable=True),
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('source_key', sa.String(length=200), nullable=False),
    sa.Column('category_external_id', sa.String(length=120), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('source', sa.Enum('manual', 'embedding', 'llm', 'imported', name='mappingsource', native_enum=False, length=32), nullable=False),
    sa.Column('hit_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_category_mappings_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_category_mappings')),
    sa.UniqueConstraint('workspace_id', 'platform', 'source_key', name='uq_category_mappings_workspace_platform_key')
    )
    op.create_index('ix_category_mappings_platform_key', 'category_mappings', ['platform', 'source_key'], unique=False)
    op.create_index(op.f('ix_category_mappings_workspace_id'), 'category_mappings', ['workspace_id'], unique=False)
    op.create_table('marketplace_accounts',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=False),
    sa.Column('niche', sa.String(length=80), nullable=True),
    sa.Column('external_username', sa.String(length=120), nullable=True),
    sa.Column('external_user_id', sa.String(length=120), nullable=True),
    sa.Column('auth_type', sa.Enum('oauth', 'browser_session', name='accountauthtype', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'needs_reauth', 'disabled', name='accountstatus', native_enum=False, length=32), nullable=False),
    sa.Column('encrypted_credentials', sa.Text(), nullable=True),
    sa.Column('credentials_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('browser_profile_key', sa.String(length=200), nullable=True),
    sa.Column('last_health_check_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_action_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('daily_action_count', sa.Integer(), nullable=False),
    sa.Column('daily_action_reset_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('settings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_marketplace_accounts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_marketplace_accounts')),
    sa.UniqueConstraint('workspace_id', 'platform', 'label', name='uq_marketplace_accounts_workspace_label')
    )
    op.create_index(op.f('ix_marketplace_accounts_workspace_id'), 'marketplace_accounts', ['workspace_id'], unique=False)
    op.create_index('ix_marketplace_accounts_workspace_platform', 'marketplace_accounts', ['workspace_id', 'platform'], unique=False)
    op.create_table('password_reset_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_password_reset_tokens_token_hash'))
    )
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.create_table('quick_replies',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('usage_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_quick_replies_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quick_replies'))
    )
    op.create_index(op.f('ix_quick_replies_workspace_id'), 'quick_replies', ['workspace_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('jti', sa.String(length=64), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('jti', name=op.f('uq_refresh_tokens_jti'))
    )
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('workspace_members',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Enum('owner', 'admin', 'member', name='workspacerole', native_enum=False, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_workspace_members_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workspace_members_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspace_members')),
    sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_members_workspace_user')
    )
    op.create_index(op.f('ix_workspace_members_user_id'), 'workspace_members', ['user_id'], unique=False)
    op.create_index(op.f('ix_workspace_members_workspace_id'), 'workspace_members', ['workspace_id'], unique=False)
    op.create_table('ai_generations',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], name=op.f('fk_ai_generations_article_id_articles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_ai_generations_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_generations'))
    )
    op.create_index(op.f('ix_ai_generations_article_id'), 'ai_generations', ['article_id'], unique=False)
    op.create_index('ix_ai_generations_workspace_created', 'ai_generations', ['workspace_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_ai_generations_workspace_id'), 'ai_generations', ['workspace_id'], unique=False)
    op.create_table('article_photos',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=True),
    sa.Column('content_type', sa.String(length=80), nullable=False),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('phash', sa.String(length=16), nullable=True),
    sa.Column('status', sa.Enum('uploaded', 'ready', 'failed', name='photostatus', native_enum=False, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], name=op.f('fk_article_photos_article_id_articles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_article_photos_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_article_photos')),
    sa.UniqueConstraint('article_id', 'position', name='uq_article_photos_article_id_position')
    )
    op.create_index(op.f('ix_article_photos_article_id'), 'article_photos', ['article_id'], unique=False)
    op.create_index('ix_article_photos_workspace_checksum', 'article_photos', ['workspace_id', 'checksum_sha256'], unique=False)
    op.create_index(op.f('ix_article_photos_workspace_id'), 'article_photos', ['workspace_id'], unique=False)
    op.create_table('price_suggestions',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.Enum('vinted', 'leboncoin', 'depop', 'ebay', name='platform', native_enum=False, length=32), nullable=False),
    sa.Column('low_cents', sa.Integer(), nullable=False),
    sa.Column('median_cents', sa.Integer(), nullable=False),
    sa.Column('high_cents', sa.Integer(), nullable=False),
    sa.Column('sample_size', sa.Integer(), nullable=False),
    sa.Column('comparables', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], name=op.f('fk_price_suggestions_article_id_articles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_price_suggestions_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_suggestions'))
    )
    op.create_index('ix_price_suggestions_article_platform', 'price_suggestions', ['article_id', 'platform'], unique=False)
    op.create_index(op.f('ix_price_suggestions_workspace_id'), 'price_suggestions', ['workspace_id'], unique=False)
    op.create_table('publications',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=False),
    sa.Column('marketplace_account_id', sa.Uuid(), nullable=False),
    sa.Column('mode', sa.Enum('draft', 'autopublish', name='publicationmode', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'queued', 'running', 'draft_ready', 'published', 'failed', 'sold', 'unpublished', name='publicationstatus', native_enum=False, length=32), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price_cents', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('remote_listing_id', sa.String(length=120), nullable=True),
    sa.Column('remote_url', sa.String(length=500), nullable=True),
    sa.Column('remote_category_id', sa.String(length=120), nullable=True),
    sa.Column('remote_brand_id', sa.String(length=120), nullable=True),
    sa.Column('remote_size_id', sa.String(length=120), nullable=True),
    sa.Column('idempotency_key', sa.String(length=80), nullable=False),
    sa.Column('checkpoint', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sold_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('unpublished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_relisted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('views_count', sa.Integer(), nullable=False),
    sa.Column('favorites_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('price_cents > 0', name=op.f('ck_publications_price_positive')),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], name=op.f('fk_publications_article_id_articles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['marketplace_account_id'], ['marketplace_accounts.id'], name=op.f('fk_publications_marketplace_account_id_marketplace_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_publications_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publications')),
    sa.UniqueConstraint('article_id', 'marketplace_account_id', name='uq_publications_article_account'),
    sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_publications_workspace_idempotency')
    )
    op.create_index(op.f('ix_publications_article_id'), 'publications', ['article_id'], unique=False)
    op.create_index(op.f('ix_publications_marketplace_account_id'), 'publications', ['marketplace_account_id'], unique=False)
    op.create_index(op.f('ix_publications_remote_listing_id'), 'publications', ['remote_listing_id'], unique=False)
    op.create_index(op.f('ix_publications_status'), 'publications', ['status'], unique=False)
    op.create_index(op.f('ix_publications_workspace_id'), 'publications', ['workspace_id'], unique=False)
    op.create_index('ix_publications_workspace_status', 'publications', ['workspace_id', 'status'], unique=False)
    op.create_table('message_threads',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('marketplace_account_id', sa.Uuid(), nullable=False),
    sa.Column('publication_id', sa.Uuid(), nullable=True),
    sa.Column('remote_thread_id', sa.String(length=120), nullable=False),
    sa.Column('counterparty_name', sa.String(length=120), nullable=True),
    sa.Column('subject', sa.String(length=255), nullable=True),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('unread_count', sa.Integer(), nullable=False),
    sa.Column('is_archived', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['marketplace_account_id'], ['marketplace_accounts.id'], name=op.f('fk_message_threads_marketplace_account_id_marketplace_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], name=op.f('fk_message_threads_publication_id_publications'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_message_threads_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_message_threads')),
    sa.UniqueConstraint('marketplace_account_id', 'remote_thread_id', name='uq_message_threads_account_remote')
    )
    op.create_index(op.f('ix_message_threads_last_message_at'), 'message_threads', ['last_message_at'], unique=False)
    op.create_index(op.f('ix_message_threads_marketplace_account_id'), 'message_threads', ['marketplace_account_id'], unique=False)
    op.create_index(op.f('ix_message_threads_publication_id'), 'message_threads', ['publication_id'], unique=False)
    op.create_index(op.f('ix_message_threads_workspace_id'), 'message_threads', ['workspace_id'], unique=False)
    op.create_table('photo_variants',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=False),
    sa.Column('source_photo_id', sa.Uuid(), nullable=False),
    sa.Column('publication_id', sa.Uuid(), nullable=True),
    sa.Column('variant_index', sa.Integer(), nullable=False),
    sa.Column('seed', sa.BigInteger(), nullable=False),
    sa.Column('recipe', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=True),
    sa.Column('content_type', sa.String(length=80), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('phash', sa.String(length=16), nullable=True),
    sa.Column('phash_distance_to_source', sa.Integer(), nullable=True),
    sa.Column('background_replaced', sa.Boolean(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'ready', 'failed', 'accepted', 'rejected', name='variantstatus', native_enum=False, length=32), nullable=False),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('render_count', sa.Integer(), nullable=False),
    sa.Column('render_ms', sa.Integer(), nullable=True),
    sa.Column('rendered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], name=op.f('fk_photo_variants_article_id_articles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], name=op.f('fk_photo_variants_publication_id_publications'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_photo_id'], ['article_photos.id'], name=op.f('fk_photo_variants_source_photo_id_article_photos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_photo_variants_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_photo_variants')),
    sa.UniqueConstraint('source_photo_id', 'variant_index', name='uq_photo_variants_photo_index')
    )
    op.create_index(op.f('ix_photo_variants_article_id'), 'photo_variants', ['article_id'], unique=False)
    op.create_index(op.f('ix_photo_variants_publication_id'), 'photo_variants', ['publication_id'], unique=False)
    op.create_index(op.f('ix_photo_variants_source_photo_id'), 'photo_variants', ['source_photo_id'], unique=False)
    op.create_index(op.f('ix_photo_variants_status'), 'photo_variants', ['status'], unique=False)
    op.create_index(op.f('ix_photo_variants_workspace_id'), 'photo_variants', ['workspace_id'], unique=False)
    op.create_index('ix_photo_variants_workspace_status', 'photo_variants', ['workspace_id', 'status'], unique=False)
    op.create_table('publication_events',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('publication_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.Enum('created', 'queued', 'step_completed', 'draft_ready', 'published', 'failed', 'retried', 'price_updated', 'relisted', 'sold', 'unpublished', name='publicationeventtype', native_enum=False, length=32), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], name=op.f('fk_publication_events_publication_id_publications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_publication_events_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publication_events'))
    )
    op.create_index('ix_publication_events_publication_created', 'publication_events', ['publication_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_publication_events_workspace_id'), 'publication_events', ['workspace_id'], unique=False)
    op.create_table('publication_schedules',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('publication_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('steps', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('step_index', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['publication_id'], ['publications.id'], name=op.f('fk_publication_schedules_publication_id_publications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_publication_schedules_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publication_schedules'))
    )
    op.create_index(op.f('ix_publication_schedules_next_run_at'), 'publication_schedules', ['next_run_at'], unique=False)
    op.create_index(op.f('ix_publication_schedules_publication_id'), 'publication_schedules', ['publication_id'], unique=False)
    op.create_index(op.f('ix_publication_schedules_workspace_id'), 'publication_schedules', ['workspace_id'], unique=False)
    op.create_table('messages',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('thread_id', sa.Uuid(), nullable=False),
    sa.Column('remote_message_id', sa.String(length=120), nullable=True),
    sa.Column('direction', sa.Enum('inbound', 'outbound', name='messagedirection', native_enum=False, length=32), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('offer_price_cents', sa.Integer(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], name=op.f('fk_messages_thread_id_message_threads'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_messages_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
    sa.UniqueConstraint('thread_id', 'remote_message_id', name='uq_messages_thread_remote')
    )
    op.create_index(op.f('ix_messages_thread_id'), 'messages', ['thread_id'], unique=False)
    op.create_index(op.f('ix_messages_workspace_id'), 'messages', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_messages_workspace_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_thread_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_publication_schedules_workspace_id'), table_name='publication_schedules')
    op.drop_index(op.f('ix_publication_schedules_publication_id'), table_name='publication_schedules')
    op.drop_index(op.f('ix_publication_schedules_next_run_at'), table_name='publication_schedules')
    op.drop_table('publication_schedules')
    op.drop_index(op.f('ix_publication_events_workspace_id'), table_name='publication_events')
    op.drop_index('ix_publication_events_publication_created', table_name='publication_events')
    op.drop_table('publication_events')
    op.drop_index('ix_photo_variants_workspace_status', table_name='photo_variants')
    op.drop_index(op.f('ix_photo_variants_workspace_id'), table_name='photo_variants')
    op.drop_index(op.f('ix_photo_variants_status'), table_name='photo_variants')
    op.drop_index(op.f('ix_photo_variants_source_photo_id'), table_name='photo_variants')
    op.drop_index(op.f('ix_photo_variants_publication_id'), table_name='photo_variants')
    op.drop_index(op.f('ix_photo_variants_article_id'), table_name='photo_variants')
    op.drop_table('photo_variants')
    op.drop_index(op.f('ix_message_threads_workspace_id'), table_name='message_threads')
    op.drop_index(op.f('ix_message_threads_publication_id'), table_name='message_threads')
    op.drop_index(op.f('ix_message_threads_marketplace_account_id'), table_name='message_threads')
    op.drop_index(op.f('ix_message_threads_last_message_at'), table_name='message_threads')
    op.drop_table('message_threads')
    op.drop_index('ix_publications_workspace_status', table_name='publications')
    op.drop_index(op.f('ix_publications_workspace_id'), table_name='publications')
    op.drop_index(op.f('ix_publications_status'), table_name='publications')
    op.drop_index(op.f('ix_publications_remote_listing_id'), table_name='publications')
    op.drop_index(op.f('ix_publications_marketplace_account_id'), table_name='publications')
    op.drop_index(op.f('ix_publications_article_id'), table_name='publications')
    op.drop_table('publications')
    op.drop_index(op.f('ix_price_suggestions_workspace_id'), table_name='price_suggestions')
    op.drop_index('ix_price_suggestions_article_platform', table_name='price_suggestions')
    op.drop_table('price_suggestions')
    op.drop_index(op.f('ix_article_photos_workspace_id'), table_name='article_photos')
    op.drop_index('ix_article_photos_workspace_checksum', table_name='article_photos')
    op.drop_index(op.f('ix_article_photos_article_id'), table_name='article_photos')
    op.drop_table('article_photos')
    op.drop_index(op.f('ix_ai_generations_workspace_id'), table_name='ai_generations')
    op.drop_index('ix_ai_generations_workspace_created', table_name='ai_generations')
    op.drop_index(op.f('ix_ai_generations_article_id'), table_name='ai_generations')
    op.drop_table('ai_generations')
    op.drop_index(op.f('ix_workspace_members_workspace_id'), table_name='workspace_members')
    op.drop_index(op.f('ix_workspace_members_user_id'), table_name='workspace_members')
    op.drop_table('workspace_members')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_quick_replies_workspace_id'), table_name='quick_replies')
    op.drop_table('quick_replies')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_index('ix_marketplace_accounts_workspace_platform', table_name='marketplace_accounts')
    op.drop_index(op.f('ix_marketplace_accounts_workspace_id'), table_name='marketplace_accounts')
    op.drop_table('marketplace_accounts')
    op.drop_index(op.f('ix_category_mappings_workspace_id'), table_name='category_mappings')
    op.drop_index('ix_category_mappings_platform_key', table_name='category_mappings')
    op.drop_table('category_mappings')
    op.drop_index(op.f('ix_brand_mappings_workspace_id'), table_name='brand_mappings')
    op.drop_table('brand_mappings')
    op.drop_index('ix_articles_workspace_status', table_name='articles')
    op.drop_index(op.f('ix_articles_workspace_id'), table_name='articles')
    op.drop_index(op.f('ix_articles_status'), table_name='articles')
    op.drop_index(op.f('ix_articles_deleted_at'), table_name='articles')
    op.drop_index(op.f('ix_articles_brand'), table_name='articles')
    op.drop_table('articles')
    op.drop_table('workspaces')
    op.drop_table('users')
    op.drop_index('ix_platform_sizes_platform_group', table_name='platform_sizes')
    op.drop_table('platform_sizes')
    op.drop_index('ix_platform_categories_platform_leaf', table_name='platform_categories')
    op.drop_index(op.f('ix_platform_categories_parent_external_id'), table_name='platform_categories')
    op.drop_table('platform_categories')
    op.drop_index('ix_platform_brands_platform_normalized', table_name='platform_brands')
    op.drop_table('platform_brands')
