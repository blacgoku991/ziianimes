"""Frais de plateforme et marge nette.

Point signalé comme manquant dans la revue de spécification : un tableau de
bord qui affiche « marge » sans modéliser les commissions, les frais de
paiement et le port à la charge du vendeur affiche un chiffre faux. Une
marge fausse est pire qu'une marge absente — elle oriente les décisions
d'achat du revendeur dans le mauvais sens.

Les barèmes ci-dessous sont des **valeurs par défaut plausibles**, pas une
vérité contractuelle : ils changent régulièrement et diffèrent entre
comptes particuliers et professionnels. Ils sont surchargeables par espace
de travail via `workspaces.settings["fees"]`, et c'est la surcharge qui
doit faire foi une fois le compte réel connu.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import Platform


@dataclass(frozen=True)
class FeeSchedule:
    """Barème d'une plateforme, du point de vue **vendeur**."""

    #: Commission sur le prix de vente, en pourcentage.
    commission_pct: float = 0.0
    #: Part fixe prélevée par transaction, en centimes.
    fixed_fee_cents: int = 0
    #: Frais d'encaissement (prestataire de paiement), en pourcentage.
    payment_pct: float = 0.0
    #: Port restant à la charge du vendeur, en centimes.
    default_shipping_cents: int = 0

    def fee_cents(self, price_cents: int) -> int:
        variable = price_cents * (self.commission_pct + self.payment_pct) / 100.0
        return int(round(variable)) + self.fixed_fee_cents

    def net_proceeds_cents(self, price_cents: int, *, shipping_cents: int | None = None) -> int:
        shipping = self.default_shipping_cents if shipping_cents is None else shipping_cents
        return price_cents - self.fee_cents(price_cents) - shipping


#: Barèmes par défaut. À confirmer compte par compte avant de s'en servir
#: pour piloter des décisions d'achat.
DEFAULT_SCHEDULES: dict[Platform, FeeSchedule] = {
    # Vinted ne prélève pas de commission au vendeur particulier : ce sont
    # les options de mise en avant, facultatives, qui coûtent.
    Platform.vinted: FeeSchedule(commission_pct=0.0, payment_pct=0.0),
    # Leboncoin : dépôt gratuit pour un particulier, options payantes.
    Platform.leboncoin: FeeSchedule(commission_pct=0.0, payment_pct=0.0),
    Platform.depop: FeeSchedule(commission_pct=10.0, payment_pct=3.3, fixed_fee_cents=25),
    Platform.ebay: FeeSchedule(commission_pct=11.0, payment_pct=0.0, fixed_fee_cents=30),
}


def schedule_for(platform: Platform, workspace_settings: dict | None = None) -> FeeSchedule:
    """Barème applicable, surcharge de l'espace de travail prioritaire."""
    base = DEFAULT_SCHEDULES.get(platform, FeeSchedule())
    override = ((workspace_settings or {}).get("fees") or {}).get(platform.value)
    if not isinstance(override, dict):
        return base
    return FeeSchedule(
        commission_pct=float(override.get("commission_pct", base.commission_pct)),
        fixed_fee_cents=int(override.get("fixed_fee_cents", base.fixed_fee_cents)),
        payment_pct=float(override.get("payment_pct", base.payment_pct)),
        default_shipping_cents=int(
            override.get("default_shipping_cents", base.default_shipping_cents)
        ),
    )


@dataclass
class MarginBreakdown:
    price_cents: int
    fee_cents: int
    shipping_cents: int
    net_proceeds_cents: int
    purchase_cost_cents: int
    margin_cents: int
    margin_pct: float

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def compute_margin(
    *,
    platform: Platform,
    price_cents: int,
    purchase_cost_cents: int,
    shipping_cents: int | None = None,
    workspace_settings: dict | None = None,
) -> MarginBreakdown:
    schedule = schedule_for(platform, workspace_settings)
    shipping = schedule.default_shipping_cents if shipping_cents is None else shipping_cents
    fee = schedule.fee_cents(price_cents)
    net = price_cents - fee - shipping
    margin = net - purchase_cost_cents
    # Marge rapportée au produit net encaissé : c'est ce que le revendeur
    # compare d'une pièce à l'autre. Rapportée au coût d'achat, un article
    # trouvé à 1 € afficherait des pourcentages absurdes.
    margin_pct = (margin / net * 100.0) if net > 0 else 0.0
    return MarginBreakdown(
        price_cents=price_cents,
        fee_cents=fee,
        shipping_cents=shipping,
        net_proceeds_cents=net,
        purchase_cost_cents=purchase_cost_cents,
        margin_cents=margin,
        margin_pct=round(margin_pct, 2),
    )


def price_for_target_margin(
    *,
    platform: Platform,
    purchase_cost_cents: int,
    target_margin_pct: float,
    shipping_cents: int | None = None,
    workspace_settings: dict | None = None,
) -> int:
    """Prix d'affichage atteignant la marge nette visée, frais compris."""
    schedule = schedule_for(platform, workspace_settings)
    shipping = schedule.default_shipping_cents if shipping_cents is None else shipping_cents
    target = min(max(target_margin_pct, 0.0), 95.0) / 100.0

    # net = prix × (1 - taux_variable) - fixe - port
    # marge = net - coût, et marge = target × net
    #   ⟹ net = coût / (1 - target)
    variable = (schedule.commission_pct + schedule.payment_pct) / 100.0
    required_net = purchase_cost_cents / (1.0 - target) if target < 1.0 else purchase_cost_cents
    price = (required_net + schedule.fixed_fee_cents + shipping) / max(1e-6, 1.0 - variable)
    return max(100, int(round(price)))
