"""Pydantic models for the Alpen Platform tenant configuration.

Two top-level shapes are validated:

  1. tenants/<id>/config.yaml      — full tenant configuration
  2. tenants/<id>/placeholders.yaml — ~~placeholder substitution pack

The schema mirrors `Alpen-platform-v0.1-architecture.md` and enforces
the storage and instrumentation rules from the feedback memories.

Validation philosophy: errors are LOUD on missing required fields and
malformed structure, but PERMISSIVE on extra/forward-compat fields.
This lets tenants extend their config without breaking older platform
versions. Set `model_config = {"extra": "forbid"}` only on terminal
shapes that should be locked.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ──────────────────────────────────────────────────────────────────────────────
# Common types
# ──────────────────────────────────────────────────────────────────────────────

EntityType = Literal[
    "ai-consulting", "brain-health-consulting", "family-office",
    "general-consulting", "saas", "agency",
]

PrincipalRole = Literal["ceo", "partner", "employee", "advisor", "other"]

DepartmentName = Literal[
    "office-of-principal", "finance", "investments", "legal",
    "revenue", "delivery", "knowledge", "operations",
]

ModelTier = Literal["sonnet", "haiku", "opus"]

RAGBackend = Literal["sqlite-vec", "pinecone", "chroma", "qdrant"]
StructuredBackend = Literal["sqlite", "postgres"]
VaultBackend = Literal["filesystem", "s3", "gdrive", "webdav"]

EmailProvider = Literal["google-workspace", "microsoft-365", "fastmail", "imap"]
TranscriptionProvider = Literal["whisper-cpp", "openai", "deepgram", "rev"]


# ──────────────────────────────────────────────────────────────────────────────
# Sub-models — placeholders.yaml
# ──────────────────────────────────────────────────────────────────────────────

class PlaceholderPack(BaseModel):
    """tenants/<id>/placeholders.yaml — placeholder substitution values."""
    schema_version: str
    tenant: str
    last_updated: date | str | None = None
    upstream: dict[str, str | int | float | None] = Field(default_factory=dict)
    alpen_extensions: dict[str, str | int | float | None] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, v: str) -> str:
        # Accept 0.1, 0.2, ... but warn loudly if not in known set
        if v not in {"0.1"}:
            raise ValueError(f"unsupported schema_version {v!r}; supported: 0.1")
        return v


# ──────────────────────────────────────────────────────────────────────────────
# Sub-models — config.yaml
# ──────────────────────────────────────────────────────────────────────────────

class TenantSection(BaseModel):
    id: str
    name: str
    type: EntityType
    timezone: str
    locale: str
    vault_path: str
    state_dir: str
    log_dir: str
    created_at: date | str

    @field_validator("id")
    @classmethod
    def lowercase_kebab(cls, v: str) -> str:
        if not v.replace("-", "").isalnum() or v != v.lower():
            raise ValueError(f"tenant.id must be lowercase kebab-case, got {v!r}")
        return v


class AccountRef(BaseModel):
    kind: str
    address: str | None = None
    handle: str | None = None
    mcp: str

    @model_validator(mode="after")
    def address_or_handle(self) -> "AccountRef":
        if not (self.address or self.handle):
            raise ValueError("AccountRef must have either address or handle")
        return self


class Principal(BaseModel):
    id: str
    name: str
    role: PrincipalRole
    scopes: list[str] = Field(min_length=1)
    accounts: list[AccountRef] = Field(default_factory=list)


class Tier(BaseModel):
    id: str
    range: tuple[int, int] | None = None
    cadence: str
    type: str | None = None  # "subscription" | "project" — optional


class Brand(BaseModel):
    voice_guide: str | None = None
    no_em_dash: bool | None = None
    newsletter: dict | None = None
    tagline: str | None = None
    model_config = ConfigDict(extra="allow")


class ICP(BaseModel):
    titles: list[str] = Field(default_factory=list)
    headcount_range: tuple[int, int] | None = None
    industries: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)


class Entity(BaseModel):
    id: str
    display_name: str
    type: EntityType
    domain: str | None = None
    public: bool = True
    icp: ICP | None = None
    tiers: list[Tier] = Field(default_factory=list)
    brand: Brand | None = None
    templates_dir: str | None = None


class DepartmentConfig(BaseModel):
    enabled: bool = True
    model: ModelTier
    scopes: list[str] | None = None
    private_to: list[str] | None = None


class RAGKind(BaseModel):
    id: str
    private: bool = False
    scopes: list[str] | None = None
    acl: list[str] | None = None


class RAGStore(BaseModel):
    backend: RAGBackend
    embedding: dict
    db_path: str
    kinds: list[RAGKind] = Field(default_factory=list)


class StructuredDB(BaseModel):
    id: str
    path: str
    private_to: list[str] | None = None


class StructuredStore(BaseModel):
    backend: StructuredBackend
    db_dir: str
    databases: list[StructuredDB] = Field(default_factory=list)


class VaultStore(BaseModel):
    backend: VaultBackend
    path: str
    layout: str = "by-entity"
    indices_dir: str | None = None
    sync_excluded: list[str] = Field(default_factory=list)
    encryption: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_excluded_for_filesystem(self) -> "VaultStore":
        # PER feedback_alpen_storage_patterns.md rule 1:
        # If vault is filesystem AND on iCloud, MUST declare sync_excluded
        # to prevent SQLite corruption.
        if self.backend == "filesystem":
            on_icloud = "iCloud" in self.path or "Mobile Documents" in self.path
            if on_icloud and not any(p.endswith(".db") or "*.db" in p for p in self.sync_excluded):
                raise ValueError(
                    "vault on iCloud must declare sync_excluded with a *.db pattern "
                    "(see feedback_alpen_storage_patterns.md rule 1)"
                )
        return self


class BackupConfig(BaseModel):
    nightly_targets: list[str] = Field(default_factory=list)
    weekly_targets: list[str] = Field(default_factory=list)
    destination: str

    @field_validator("destination")
    @classmethod
    def destination_not_tcc_protected(cls, v: str) -> str:
        # PER nightly-backup.sh learning: launchd cannot write to
        # ~/Library/Mobile Documents OR ~/Documents on modern macOS.
        protected_substrings = ["Mobile Documents", "Documents/", "Documents$"]
        for protected in protected_substrings:
            if protected.replace("$", "") in v:
                raise ValueError(
                    f"backup destination {v!r} appears to be in a TCC-protected "
                    f"path (~/Documents or ~/Library/Mobile Documents/). launchd "
                    f"cannot write here without granting bash Full Disk Access. "
                    f"Use ~/Winnie/backups/ or another non-protected location."
                )
        return v


class DataStores(BaseModel):
    rag: RAGStore
    structured: StructuredStore
    vault: VaultStore
    backup: BackupConfig | None = None


class TelemetryPrivacy(BaseModel):
    redact_pii_in_summaries: bool = True
    excluded_kinds: list[str] = Field(default_factory=list)


class TelemetryConfig(BaseModel):
    enabled: bool = True
    ledger: str
    sqlite: str
    dashboard: dict | None = None
    expose_to_principal: bool = True
    expose_to_customer: bool = False
    privacy: TelemetryPrivacy = Field(default_factory=TelemetryPrivacy)


class Schedule(BaseModel):
    id: str
    cron: str | None = None
    agent: str
    runtime: str | None = None
    scopes: list[str] | None = None


class Watchpath(BaseModel):
    path: str
    agent: str
    scopes: list[str] | None = None


class Schedules(BaseModel):
    cron: list[Schedule] = Field(default_factory=list)
    watchpaths: list[Watchpath] = Field(default_factory=list)


class TenantConfig(BaseModel):
    """tenants/<id>/config.yaml — full tenant configuration."""
    schema_version: str
    tenant: TenantSection
    principals: list[Principal] = Field(min_length=1)
    entities: list[Entity] = Field(min_length=1)
    departments: dict[str, DepartmentConfig]
    data_stores: DataStores
    integrations: dict
    templates: dict | None = None
    telemetry: TelemetryConfig
    schedules: Schedules | None = None
    features: dict = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, v: str) -> str:
        if v not in {"0.1"}:
            raise ValueError(f"unsupported schema_version {v!r}; supported: 0.1")
        return v

    @model_validator(mode="after")
    def departments_use_canonical_names(self) -> "TenantConfig":
        canonical = {
            "office-of-principal", "finance", "investments", "legal",
            "revenue", "delivery", "knowledge", "operations",
        }
        for name in self.departments:
            if name not in canonical:
                raise ValueError(
                    f"unknown department {name!r}; valid: {sorted(canonical)}"
                )
        return self

    @model_validator(mode="after")
    def principal_scopes_reference_entities(self) -> "TenantConfig":
        entity_ids = {e.id for e in self.entities}
        for p in self.principals:
            for s in p.scopes:
                if s not in entity_ids:
                    raise ValueError(
                        f"principal {p.id!r} references unknown entity scope {s!r}; "
                        f"defined entities: {sorted(entity_ids)}"
                    )
        return self
