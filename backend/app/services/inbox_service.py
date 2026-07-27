"""Étape 6 — boîte de réception unifiée.

Tous les comptes et toutes les plateformes dans une seule vue. Deux
attentions particulières :

* **l'ingestion est idempotente** — un message repêché deux fois par la
  synchronisation ne crée pas de doublon, l'unicité
  `(thread, remote_message_id)` s'en charge ;
* **les offres sont extraites** du corps du message quand la plateforme ne
  les expose pas séparément : une offre ratée est une vente perdue.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import MessageDirection
from app.models.marketplace import (
    MarketplaceAccount,
    Message,
    MessageThread,
    Publication,
    QuickReply,
)

logger = get_logger(__name__)

#: « je vous en propose 15 € », « 12,50€ », « 20 euros ».
_OFFER_PATTERN = re.compile(r"(\d{1,4})(?:[.,](\d{1,2}))?\s*(?:€|eur\b|euros?\b)", re.IGNORECASE)


def extract_offer_cents(body: str) -> int | None:
    """Montant proposé dans un message, en centimes."""
    match = _OFFER_PATTERN.search(body or "")
    if not match:
        return None
    units = int(match.group(1))
    cents = int((match.group(2) or "0").ljust(2, "0"))
    total = units * 100 + cents
    # Au-delà, c'est probablement autre chose qu'une offre sur un vêtement.
    return total if 100 <= total <= 500_000 else None


@dataclass
class IngestReport:
    threads_created: int = 0
    threads_updated: int = 0
    messages_created: int = 0
    offers_detected: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def ingest_threads(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    account: MarketplaceAccount,
    payload: list[dict],
) -> IngestReport:
    """Intègre les fils remontés par un connecteur."""
    report = IngestReport()
    for raw in payload:
        remote_thread_id = str(raw.get("remote_thread_id") or "").strip()
        if not remote_thread_id:
            continue

        thread = db.execute(
            sa.select(MessageThread).where(
                MessageThread.marketplace_account_id == account.id,
                MessageThread.remote_thread_id == remote_thread_id,
            )
        ).scalar_one_or_none()

        if thread is None:
            thread = MessageThread(
                workspace_id=workspace_id,
                marketplace_account_id=account.id,
                remote_thread_id=remote_thread_id,
                counterparty_name=(raw.get("counterparty_name") or "")[:120] or None,
                subject=(raw.get("subject") or "")[:255] or None,
                publication_id=_link_publication(db, workspace_id, raw.get("remote_listing_id")),
            )
            db.add(thread)
            db.flush()
            report.threads_created += 1
        else:
            if raw.get("counterparty_name"):
                thread.counterparty_name = str(raw["counterparty_name"])[:120]
            report.threads_updated += 1

        for message in raw.get("messages") or []:
            if _ingest_message(
                db, workspace_id=workspace_id, thread=thread, raw=message, report=report
            ):
                report.messages_created += 1

        # Certaines plateformes ne rendent qu'un aperçu, sans le détail.
        preview = raw.get("preview")
        if (
            preview
            and not (raw.get("messages") or [])
            and _ingest_message(
                db,
                workspace_id=workspace_id,
                thread=thread,
                raw={"body": preview, "direction": "inbound", "remote_message_id": None},
                report=report,
            )
        ):
            report.messages_created += 1

    db.flush()
    logger.info("inbox_ingested", account_id=str(account.id), **report.as_dict())
    return report


def _ingest_message(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    thread: MessageThread,
    raw: dict,
    report: IngestReport,
) -> bool:
    body = (raw.get("body") or "").strip()
    if not body:
        return False
    remote_id = raw.get("remote_message_id")
    if remote_id:
        existing = db.execute(
            sa.select(Message.id).where(
                Message.thread_id == thread.id, Message.remote_message_id == str(remote_id)
            )
        ).first()
        if existing is not None:
            return False

    direction = (
        MessageDirection.outbound
        if str(raw.get("direction", "inbound")).lower() == "outbound"
        else MessageDirection.inbound
    )
    offer = extract_offer_cents(body) if direction is MessageDirection.inbound else None
    if offer:
        report.offers_detected += 1

    db.add(
        Message(
            workspace_id=workspace_id,
            thread_id=thread.id,
            remote_message_id=str(remote_id) if remote_id else None,
            direction=direction,
            body=body[:8000],
            offer_price_cents=offer,
            sent_at=_parse_datetime(raw.get("sent_at")),
        )
    )
    thread.last_message_at = datetime.now(UTC)
    if direction is MessageDirection.inbound:
        thread.unread_count += 1
    return True


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _link_publication(
    db: Session, workspace_id: uuid.UUID, remote_listing_id: object
) -> uuid.UUID | None:
    if not remote_listing_id:
        return None
    publication = db.execute(
        sa.select(Publication.id).where(
            Publication.workspace_id == workspace_id,
            Publication.remote_listing_id == str(remote_listing_id),
        )
    ).scalar_one_or_none()
    return publication


def list_threads(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    unread_only: bool = False,
    with_offers_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    conditions = [
        MessageThread.workspace_id == workspace_id,
        MessageThread.is_archived.is_(False),
    ]
    if account_id is not None:
        conditions.append(MessageThread.marketplace_account_id == account_id)
    if unread_only:
        conditions.append(MessageThread.unread_count > 0)

    rows = db.execute(
        sa.select(MessageThread, MarketplaceAccount)
        .join(MarketplaceAccount, MarketplaceAccount.id == MessageThread.marketplace_account_id)
        .where(*conditions)
        .order_by(MessageThread.last_message_at.desc().nullslast())
        .limit(min(limit, 200))
    ).all()

    threads = []
    for thread, account in rows:
        last = db.execute(
            sa.select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        best_offer = db.execute(
            sa.select(sa.func.max(Message.offer_price_cents)).where(Message.thread_id == thread.id)
        ).scalar_one()
        if with_offers_only and not best_offer:
            continue
        threads.append(
            {
                "id": str(thread.id),
                "account_id": str(account.id),
                "account_label": account.label,
                "platform": account.platform.value,
                "counterparty_name": thread.counterparty_name,
                "subject": thread.subject,
                "unread_count": thread.unread_count,
                "last_message_at": (
                    thread.last_message_at.isoformat() if thread.last_message_at else None
                ),
                "last_message_preview": (last.body[:200] if last else None),
                "best_offer_cents": int(best_offer) if best_offer else None,
                "publication_id": str(thread.publication_id) if thread.publication_id else None,
            }
        )
    return threads


def thread_messages(db: Session, *, workspace_id: uuid.UUID, thread_id: uuid.UUID) -> list[dict]:
    thread = db.execute(
        sa.select(MessageThread).where(
            MessageThread.id == thread_id, MessageThread.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFoundError("conversation introuvable")

    messages = list(
        db.execute(
            sa.select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at.asc())
        )
        .scalars()
        .all()
    )
    thread.unread_count = 0
    db.flush()
    return [
        {
            "id": str(message.id),
            "direction": message.direction.value,
            "body": message.body,
            "offer_price_cents": message.offer_price_cents,
            "sent_at": message.sent_at.isoformat() if message.sent_at else None,
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]


def queue_reply(db: Session, *, workspace_id: uuid.UUID, thread_id: uuid.UUID, body: str) -> dict:
    """Enregistre une réponse à envoyer.

    L'envoi effectif passe par le connecteur du compte, donc par la file :
    il compte comme une action et respecte la cadence du compte au même
    titre qu'une publication.
    """
    if not body.strip():
        raise ValidationError("message vide")
    thread = db.execute(
        sa.select(MessageThread).where(
            MessageThread.id == thread_id, MessageThread.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFoundError("conversation introuvable")

    message = Message(
        workspace_id=workspace_id,
        thread_id=thread.id,
        direction=MessageDirection.outbound,
        body=body.strip()[:8000],
    )
    db.add(message)
    thread.last_message_at = datetime.now(UTC)
    db.flush()
    return {"id": str(message.id), "queued": True}


# ---------------------------------------------------------------------------
# Réponses rapides
# ---------------------------------------------------------------------------


def list_quick_replies(db: Session, *, workspace_id: uuid.UUID) -> list[QuickReply]:
    return list(
        db.execute(
            sa.select(QuickReply)
            .where(QuickReply.workspace_id == workspace_id)
            .order_by(QuickReply.usage_count.desc(), QuickReply.label)
        )
        .scalars()
        .all()
    )


def create_quick_reply(
    db: Session, *, workspace_id: uuid.UUID, label: str, body: str
) -> QuickReply:
    if not label.strip() or not body.strip():
        raise ValidationError("libellé et contenu sont requis")
    reply = QuickReply(workspace_id=workspace_id, label=label.strip()[:80], body=body.strip())
    db.add(reply)
    db.flush()
    return reply


def use_quick_reply(db: Session, *, workspace_id: uuid.UUID, reply_id: uuid.UUID) -> QuickReply:
    reply = db.execute(
        sa.select(QuickReply).where(
            QuickReply.id == reply_id, QuickReply.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if reply is None:
        raise NotFoundError("réponse rapide introuvable")
    reply.usage_count += 1
    db.flush()
    return reply


DEFAULT_QUICK_REPLIES = [
    ("Disponible", "Bonjour, oui l'article est toujours disponible."),
    ("Mesures", "Bonjour, je vous envoie les mesures à plat dans la journée."),
    (
        "Offre refusée",
        "Merci pour votre proposition. Je ne peux pas descendre à ce prix, "
        "mais je reste ouvert à une offre intermédiaire.",
    ),
    ("Envoi", "Bonjour, l'envoi est fait sous 24 h après réception du paiement."),
]


def seed_quick_replies(db: Session, *, workspace_id: uuid.UUID) -> int:
    """Réponses de départ, pour que la boîte serve dès le premier message."""
    existing = db.execute(
        sa.select(sa.func.count())
        .select_from(QuickReply)
        .where(QuickReply.workspace_id == workspace_id)
    ).scalar_one()
    if existing:
        return 0
    for label, body in DEFAULT_QUICK_REPLIES:
        db.add(QuickReply(workspace_id=workspace_id, label=label, body=body))
    db.flush()
    return len(DEFAULT_QUICK_REPLIES)
