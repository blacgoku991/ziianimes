"""Résolution du connecteur d'un compte."""

from __future__ import annotations

from app.connectors.base import Connector
from app.core.errors import ValidationError
from app.models.enums import Platform
from app.models.marketplace import MarketplaceAccount

#: Connecteur de remplacement, injectable par les tests et le mode
#: démonstration : il permet de dérouler tout le moteur de publication —
#: file, reprise, dépublication croisée — sans toucher à une plateforme.
_override: dict[Platform, Connector] = {}


def set_connector_override(platform: Platform, connector: Connector | None) -> None:
    if connector is None:
        _override.pop(platform, None)
    else:
        _override[platform] = connector


def clear_overrides() -> None:
    _override.clear()


def get_connector(account: MarketplaceAccount) -> Connector:
    if account.platform in _override:
        return _override[account.platform]

    if account.platform is Platform.vinted:
        from app.connectors.vinted.connector import VintedConnector
        from app.services.account_service import browser_profile_dir

        return VintedConnector(profile_dir=str(browser_profile_dir(account)))

    from app.connectors.api_based import DepopConnector, EbayConnector, LeboncoinConnector

    mapping = {
        Platform.ebay: EbayConnector,
        Platform.depop: DepopConnector,
        Platform.leboncoin: LeboncoinConnector,
    }
    factory = mapping.get(account.platform)
    if factory is None:
        raise ValidationError(f"aucun connecteur pour {account.platform.value}")
    return factory()
