from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


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
