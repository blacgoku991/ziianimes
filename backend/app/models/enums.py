"""Énumérations métier.

Elles sont persistées en `VARCHAR + CHECK` (``native_enum=False``) et non en
type ENUM natif Postgres : ajouter une valeur ne demande alors qu'un
remplacement de contrainte, pas un `ALTER TYPE` non transactionnel.
"""

from __future__ import annotations

import enum


class WorkspaceRole(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"


class SubscriptionStatus(enum.StrEnum):
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"
    incomplete = "incomplete"


class ArticleStatus(enum.StrEnum):
    draft = "draft"
    listed = "listed"
    #: Vendu sur une plateforme, dépublication des autres en cours.
    reserved = "reserved"
    sold = "sold"
    #: Retour acheteur : la pièce revient en stock.
    returned = "returned"
    withdrawn = "withdrawn"


class ArticleCondition(enum.StrEnum):
    new_with_tags = "new_with_tags"
    new_without_tags = "new_without_tags"
    very_good = "very_good"
    good = "good"
    fair = "fair"


class PhotoStatus(enum.StrEnum):
    uploaded = "uploaded"
    ready = "ready"
    failed = "failed"


class VariantStatus(enum.StrEnum):
    pending = "pending"
    ready = "ready"
    failed = "failed"
    accepted = "accepted"
    rejected = "rejected"


class Platform(enum.StrEnum):
    vinted = "vinted"
    leboncoin = "leboncoin"
    depop = "depop"
    ebay = "ebay"


class AccountAuthType(enum.StrEnum):
    oauth = "oauth"
    browser_session = "browser_session"


class AccountStatus(enum.StrEnum):
    active = "active"
    needs_reauth = "needs_reauth"
    disabled = "disabled"


class PublicationMode(enum.StrEnum):
    #: Le formulaire distant est rempli, l'utilisateur donne le dernier clic.
    draft = "draft"
    #: Soumission automatique de bout en bout.
    autopublish = "autopublish"


class PublicationStatus(enum.StrEnum):
    pending = "pending"
    #: Bloquée : un garde-fou métier s'y oppose (cadence, doublon de compte).
    blocked = "blocked"
    queued = "queued"
    running = "running"
    draft_ready = "draft_ready"
    published = "published"
    failed = "failed"
    sold = "sold"
    unpublished = "unpublished"


class PublicationEventType(enum.StrEnum):
    created = "created"
    queued = "queued"
    step_completed = "step_completed"
    draft_ready = "draft_ready"
    published = "published"
    failed = "failed"
    retried = "retried"
    price_updated = "price_updated"
    relisted = "relisted"
    sold = "sold"
    unpublished = "unpublished"


class MappingSource(enum.StrEnum):
    manual = "manual"
    embedding = "embedding"
    llm = "llm"
    imported = "imported"


class MessageDirection(enum.StrEnum):
    inbound = "inbound"
    outbound = "outbound"
