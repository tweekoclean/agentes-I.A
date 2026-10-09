from datetime import date, datetime, timezone
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class SalesApplication(Base):
    """Operação comercial da Nelvo, separada dos espaços de atendimento vendidos."""
    __tablename__ = "sales_applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), unique=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("support_tenants.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    segment: Mapped[str] = mapped_column(String(50))
    contact_name: Mapped[str] = mapped_column(String(150), default="")
    phone: Mapped[str | None] = mapped_column(String(20))
    channels: Mapped[list] = mapped_column(JSON, default=list)
    volume: Mapped[str] = mapped_column(String(30), default="nao_informado")
    goals: Mapped[str] = mapped_column(Text, default="")
    contact_permission: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(30), default="pesquisa")
    stage: Mapped[str] = mapped_column(String(30), default="nova", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    project: Mapped["ApplicationProject | None"] = relationship(
        lazy="selectin", uselist=False, cascade="all, delete-orphan")


class ApplicationProject(Base):
    """Detalhes adicionais; tabela nova preserva aplicações de versões anteriores."""
    __tablename__ = "application_projects"
    application_id: Mapped[str] = mapped_column(ForeignKey("sales_applications.id"), primary_key=True)
    services: Mapped[list] = mapped_column(JSON)
    state: Mapped[str | None] = mapped_column(String(2))
    website: Mapped[str] = mapped_column(String(500), default="")


class ApplicationRate(Base):
    __tablename__ = "application_rates"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("source", "source_ref", name="uq_lead_source"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(100), index=True)
    city_ibge: Mapped[str] = mapped_column(String(7))
    segment: Mapped[str] = mapped_column(String(50), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    phone_public: Mapped[str | None] = mapped_column(String(250))
    phone_normalized: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(Text)
    email_public: Mapped[str | None] = mapped_column(String(300))
    opening_hours: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50))
    source_ref: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text)
    source_license: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    review_status: Mapped[str] = mapped_column(String(30), default="pendente", index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    consent_status: Mapped[str] = mapped_column(String(30), default="desconhecido", index=True)
    whatsapp_recipient: Mapped[str | None] = mapped_column(String(20))
    analysis: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConsentEvent(Base):
    __tablename__ = "consent_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    recipient: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(100), default="oferta_atendimento_ia")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchCache(Base):
    __tablename__ = "search_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SearchRun(Base):
    __tablename__ = "search_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    city: Mapped[str] = mapped_column(String(100))
    segments: Mapped[list] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(50))
    cached: Mapped[bool] = mapped_column(Boolean)
    found: Mapped[int] = mapped_column(Integer)
    inserted: Mapped[int] = mapped_column(Integer)
    updated: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderLease(Base):
    __tablename__ = "provider_leases"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommercialConversation(Base):
    __tablename__ = "commercial_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recipient: Mapped[str] = mapped_column(String(20), unique=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), index=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_id: Mapped[str | None] = mapped_column(String(36))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(100))
    auto_replies: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommercialMessage(Base):
    __tablename__ = "commercial_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("commercial_conversations.id"), index=True)
    recipient: Mapped[str | None] = mapped_column(String(20))
    sender_id: Mapped[str | None] = mapped_column(String(25))
    direction: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), index=True)
    delivery_status: Mapped[str | None] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(250), unique=True)
    reply_to_id: Mapped[str | None] = mapped_column(ForeignKey("commercial_messages.id"), unique=True)
    opening_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    engine: Mapped[str | None] = mapped_column(String(60))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommercialHandoff(Base):
    __tablename__ = "commercial_handoffs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("commercial_conversations.id"), index=True)
    reason: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aberto", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppStatusEvent(Base):
    __tablename__ = "whatsapp_status_events"
    __table_args__ = (UniqueConstraint("provider_message_id", "status", "occurred_at", name="uq_whatsapp_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_message_id: Mapped[str] = mapped_column(String(250), index=True)
    recipient: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))


class CommercialQuota(Base):
    __tablename__ = "commercial_quotas"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    opening_attempts: Mapped[int] = mapped_column(Integer, default=0)


class SupportTenant(Base):
    __tablename__ = "support_tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    site_key_hash: Mapped[str] = mapped_column(String(64))
    allowed_origins: Mapped[list] = mapped_column(JSON)
    welcome_text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_conversation_limit: Mapped[int] = mapped_column(Integer, default=100)
    daily_ai_limit: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportKnowledge(Base):
    __tablename__ = "support_knowledge"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("support_tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportConversation(Base):
    __tablename__ = "support_conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "channel", "recipient", name="uq_support_recipient"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("support_tenants.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    recipient: Mapped[str | None] = mapped_column(String(20))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    origin: Mapped[str | None] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(30), default="bot", index=True)
    pause_reason: Mapped[str | None] = mapped_column(String(100))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_id: Mapped[str | None] = mapped_column(String(36))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_replies: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (UniqueConstraint("conversation_id", "client_message_id", name="uq_support_client_message"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("support_tenants.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("support_conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    author: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20), default="text")
    text: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[str | None] = mapped_column(String(64))
    reply_to_id: Mapped[str | None] = mapped_column(ForeignKey("support_messages.id"), unique=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(250), unique=True)
    sender_id: Mapped[str | None] = mapped_column(String(25))
    status: Mapped[str] = mapped_column(String(40), index=True)
    delivery_status: Mapped[str | None] = mapped_column(String(20))
    engine: Mapped[str | None] = mapped_column(String(60))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportHandoff(Base):
    __tablename__ = "support_handoffs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("support_tenants.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("support_conversations.id"), index=True)
    reason: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aberto", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportQuota(Base):
    __tablename__ = "support_quotas"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("support_tenants.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    conversations_opened: Mapped[int] = mapped_column(Integer, default=0)
    ai_calls: Mapped[int] = mapped_column(Integer, default=0)


def build_database(url: str, *, connect_args=None):
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if url.endswith(":memory:"):
            options["poolclass"] = StaticPool
    else:
        options["pool_size"] = 3
        options["max_overflow"] = 2
        options["connect_args"] = {"connect_timeout": 10}
    options["connect_args"].update(connect_args or {})
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
