"""Configuration applicative, lue depuis l'environnement."""

from __future__ import annotations

import base64
import functools
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application ------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = True
    api_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # -- Secrets ----------------------------------------------------------
    jwt_secret: str = "insecure-dev-secret-change-me-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 30
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30
    password_reset_ttl_seconds: int = 60 * 60

    #: Clé de chiffrement au repos (32 octets, base64 url-safe).
    #: Vide en dev => dérivée du jwt_secret, refusée en production.
    encryption_key: str = ""

    # -- Base de données --------------------------------------------------
    database_url: str = "postgresql+psycopg://ziia:ziia@localhost:5432/ziia"
    test_database_url: str = ""
    db_echo: bool = False

    # -- Tâches asynchrones ----------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_always_eager: bool = False

    # -- Stockage ---------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: str = "./var/storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_presign_ttl_seconds: int = 900

    # -- Pipeline photo ---------------------------------------------------
    image_max_upload_bytes: int = 25 * 1024 * 1024
    image_allowed_content_types: list[str] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp"]
    )
    image_output_quality: int = 93
    image_min_long_edge: int = 1600
    image_max_long_edge: int = 4096
    image_allow_upscale: bool = True
    segmentation_backend: Literal["auto", "rembg", "none"] = "auto"
    variant_min_phash_distance: int = 10
    #: Le miroir horizontal inverse logos et textes : à couper pour les
    #: niches où la marque est visible sur le vêtement.
    variant_allow_mirror: bool = True
    variant_max_render_attempts: int = 3
    max_photos_per_article: int = 20

    # -- Intelligence artificielle ----------------------------------------
    #: auto = anthropic si une clé est présente, bouchon déterministe sinon.
    ai_provider: Literal["auto", "anthropic", "stub"] = "auto"
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"
    #: Tarifs en euros par million de jetons, pour la traçabilité de coût.
    ai_input_price_per_mtok: float = 2.8
    ai_output_price_per_mtok: float = 14.0
    ai_max_photos_per_analysis: int = 4

    # -- Publication ------------------------------------------------------
    #: Délai minimal entre deux actions automatisées sur un même compte.
    publish_min_delay_seconds: int = 45
    publish_max_delay_seconds: int = 180
    #: Plafond quotidien d'actions par compte, pour rester sous les limites
    #: des plateformes.
    publish_daily_cap_per_account: int = 40
    #: Une publication à la fois par compte : durée de garde du verrou.
    publish_lock_ttl_seconds: int = 900
    publish_max_attempts: int = 3
    #: Mode brouillon imposé tant que l'espace n'a pas explicitement accepté
    #: l'avertissement CGU.
    autopublish_requires_notice: bool = True
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30_000
    #: Racine des profils navigateur, un répertoire strictement isolé par
    #: compte. À monter en tmpfs en production.
    browser_profiles_root: str = "./var/browser-profiles"

    # -- Stock et relances ------------------------------------------------
    #: Au-delà, une annonce est considérée comme dormante.
    stale_listing_days: int = 60
    #: Paliers de baisse par défaut, applicables par publication.
    default_price_drop_steps: list[dict] = Field(
        default_factory=lambda: [
            {"after_days": 21, "drop_pct": 5},
            {"after_days": 45, "drop_pct": 10},
            {"after_days": 75, "drop_pct": 15},
        ]
    )
    #: Fréquence maximale de remontée d'une même annonce.
    relist_min_interval_days: int = 7

    # -- Synchronisation --------------------------------------------------
    #: Fenêtre d'exposition à la survente : deux acheteurs peuvent acheter la
    #: même pièce entre deux synchronisations. Voir docs/REVUE_SPEC.md §1.2.
    sync_interval_seconds: int = 600

    # -- Facturation -------------------------------------------------------
    trial_period_days: int = 14

    @field_validator("cors_origins", "image_allowed_content_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accepte `a,b` autant que `["a","b"]` dans l'environnement."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "production")

    def encryption_key_bytes(self) -> bytes:
        """Clé symétrique 32 octets utilisée pour le chiffrement au repos.

        En production la clé doit être fournie explicitement : on refuse de
        dériver silencieusement un secret depuis `jwt_secret`, sinon une
        rotation du secret JWT rendrait illisibles toutes les sessions
        marketplace stockées.
        """
        if self.encryption_key:
            raw = base64.urlsafe_b64decode(_pad_b64(self.encryption_key))
            if len(raw) != 32:
                raise ValueError("ENCRYPTION_KEY doit faire 32 octets une fois décodée")
            return raw
        if self.is_production:
            raise RuntimeError("ENCRYPTION_KEY est obligatoire hors développement")
        import hashlib

        return hashlib.sha256(f"dev-kek::{self.jwt_secret}".encode()).digest()


def _pad_b64(value: str) -> str:
    return value + "=" * (-len(value) % 4)


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
