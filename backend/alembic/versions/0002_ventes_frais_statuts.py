"""Données de vente, frais réels et statuts complémentaires.

Trois ajouts, tous issus de la revue de spécification :

* le **prix réellement encaissé** et les frais associés — sans eux, la marge
  affichée est fausse et le prix conseillé n'a aucune donnée de vente sur
  laquelle s'appuyer ;
* le statut **`returned`** — un retour acheteur remet la pièce en stock, cas
  courant qui n'existait pas dans l'énumération ;
* le statut de publication **`blocked`** — une publication écartée par un
  garde-fou (cadence, doublon de compte) doit être visible comme telle,
  plutôt que silencieusement laissée en attente.

Cette révision pose aussi les contraintes `CHECK` des énumérations, que la
révision initiale n'avait pas créées : SQLAlchemy 2.0 ne les génère pas par
défaut, si bien que la validation restait purement applicative. Les workers
écrivant dans les mêmes tables que l'API, la base doit refuser une valeur
inconnue quelle qu'en soit la provenance.

Les énumérations sont stockées en `VARCHAR + CHECK` : ajouter une valeur
revient à remplacer la contrainte, opération transactionnelle et
réversible — c'est exactement ce pour quoi ce choix avait été fait.

Revision ID: 0002_ventes
Revises: 0001_initial
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "0002_ventes"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Liste **figée** des contraintes d'énumération, telle qu'elle est à cette
#: révision. Volontairement statique : une migration décrit un état de
#: l'histoire, elle ne doit pas se recalculer depuis les modèles courants —
#: sinon une évolution future en réécrirait silencieusement le sens.
_ENUM_CHECKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("platform_brands", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    ("platform_categories", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    ("platform_sizes", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    (
        "workspaces",
        "subscription_status",
        ("trialing", "active", "past_due", "canceled", "incomplete"),
    ),
    (
        "articles",
        "condition",
        ("new_with_tags", "new_without_tags", "very_good", "good", "fair"),
    ),
    ("articles", "status", ("draft", "listed", "reserved", "sold", "returned", "withdrawn")),
    ("brand_mappings", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    ("brand_mappings", "source", ("manual", "embedding", "llm", "imported")),
    ("category_mappings", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    ("category_mappings", "source", ("manual", "embedding", "llm", "imported")),
    ("marketplace_accounts", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    ("marketplace_accounts", "auth_type", ("oauth", "browser_session")),
    ("marketplace_accounts", "status", ("active", "needs_reauth", "disabled")),
    ("workspace_members", "role", ("owner", "admin", "member")),
    ("article_photos", "status", ("uploaded", "ready", "failed")),
    ("price_suggestions", "platform", ("vinted", "leboncoin", "depop", "ebay")),
    ("publications", "mode", ("draft", "autopublish")),
    (
        "publications",
        "status",
        (
            "pending",
            "blocked",
            "queued",
            "running",
            "draft_ready",
            "published",
            "failed",
            "sold",
            "unpublished",
        ),
    ),
    ("photo_variants", "status", ("pending", "ready", "failed", "accepted", "rejected")),
    (
        "publication_events",
        "event_type",
        (
            "created",
            "queued",
            "step_completed",
            "draft_ready",
            "published",
            "failed",
            "retried",
            "price_updated",
            "relisted",
            "sold",
            "unpublished",
        ),
    ),
    ("messages", "direction", ("inbound", "outbound")),
)


def upgrade() -> None:
    op.add_column("publications", sa.Column("sale_price_cents", sa.Integer(), nullable=True))
    op.add_column("publications", sa.Column("fee_cents", sa.Integer(), nullable=True))
    op.add_column("publications", sa.Column("shipping_cents", sa.Integer(), nullable=True))
    op.add_column("publications", sa.Column("net_proceeds_cents", sa.Integer(), nullable=True))
    op.add_column("publications", sa.Column("copy_variant_index", sa.Integer(), nullable=True))
    op.add_column(
        "publications",
        sa.Column("next_sync_at", app.db.types.UtcDateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_publications_next_sync_at"), "publications", ["next_sync_at"], unique=False
    )

    for table, column, values in _ENUM_CHECKS:
        op.create_check_constraint(column, table, sa.column(column).in_(values))


def downgrade() -> None:
    for table, column, _values in _ENUM_CHECKS:
        op.drop_constraint(f"ck_{table}_{column}", table, type_="check")

    op.drop_index(op.f("ix_publications_next_sync_at"), table_name="publications")
    op.drop_column("publications", "next_sync_at")
    op.drop_column("publications", "copy_variant_index")
    op.drop_column("publications", "net_proceeds_cents")
    op.drop_column("publications", "shipping_cents")
    op.drop_column("publications", "fee_cents")
    op.drop_column("publications", "sale_price_cents")
