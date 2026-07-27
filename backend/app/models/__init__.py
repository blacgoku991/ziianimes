"""Modèles ORM.

L'import de ce module enregistre toutes les tables sur `Base.metadata` :
c'est ce dont Alembic a besoin pour l'autogénération.
"""

from app.db.base import Base
from app.models.catalog import Article, ArticlePhoto, PhotoVariant
from app.models.identity import (
    PasswordResetToken,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.marketplace import (
    MarketplaceAccount,
    Message,
    MessageThread,
    Publication,
    PublicationEvent,
    PublicationSchedule,
    QuickReply,
)
from app.models.referential import (
    AiGeneration,
    BrandMapping,
    CategoryMapping,
    PlatformBrand,
    PlatformCategory,
    PlatformSize,
    PriceSuggestion,
)

__all__ = [
    "AiGeneration",
    "Article",
    "ArticlePhoto",
    "Base",
    "BrandMapping",
    "CategoryMapping",
    "MarketplaceAccount",
    "Message",
    "MessageThread",
    "PasswordResetToken",
    "PhotoVariant",
    "PlatformBrand",
    "PlatformCategory",
    "PlatformSize",
    "PriceSuggestion",
    "Publication",
    "PublicationEvent",
    "PublicationSchedule",
    "QuickReply",
    "RefreshToken",
    "User",
    "Workspace",
    "WorkspaceMember",
]
