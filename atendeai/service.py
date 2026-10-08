from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import Lead, ProviderLease, SearchCache, SearchRun, as_utc, new_id, utcnow
from .research import priority_for
from .sources import Candidate, SourceBusy


def db_insert(session, model):
    return (pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert)(model)


def eligible_for_commercial(lead):
    return (not lead.is_demo and lead.review_status == "aprovada"
            and lead.consent_status == "concedido" and bool(lead.whatsapp_recipient))


def serialize_lead(lead):
    eligible = eligible_for_commercial(lead)
    if lead.is_demo:
        status = "demonstracao"
    elif lead.review_status == "descartada":
        status = "descartada"
    elif lead.consent_status == "revogado":
        status = "contato_interrompido"
    elif lead.consent_status != "concedido":
        status = "aguardando_consentimento"
    elif not eligible:
        status = "aguardando_revisao"
    else:
        status = "pronta_para_etapa_comercial"
    return {
        "id": lead.id, "nome": lead.name, "cidade": lead.city, "uf": "SP",
        "codigo_ibge": lead.city_ibge, "segmento": lead.segment,
        "endereco_publicado": lead.address, "telefone_publicado": lead.phone_public,
        "telefone_normalizado": lead.phone_normalized,
        "telefone_publicado_confirmado_como_whatsapp": False,
        "site": lead.website, "email_publicado": lead.email_public,
        "horarios_publicados": lead.opening_hours,
        "fonte": lead.source, "referencia_fonte": lead.source_ref,
        "url_fonte": lead.source_url, "licenca_fonte": lead.source_license,
        "demonstracao": lead.is_demo, "prioridade_de_triagem": lead.priority,
        "revisao": lead.review_status, "nota_revisao": lead.review_note,
        "consentimento_whatsapp": lead.consent_status,
        "destinatario_whatsapp_autorizado": lead.whatsapp_recipient,
        "elegivel_para_etapa_comercial": eligible, "etapa": status,
        "analise": lead.analysis,
        "cadastrada_em": as_utc(lead.created_at).isoformat(),
        "dados_consultados_em": as_utc(lead.last_seen_at).isoformat(),
    }


def acquire_provider_slot(sessions, interval):
    now = utcnow()
    with sessions() as session:
        session.execute(db_insert(session, ProviderLease).values(
            name="overpass", next_allowed_at=datetime(1970, 1, 1, tzinfo=timezone.utc)
        ).on_conflict_do_nothing(index_elements=["name"]))
        result = session.execute(update(ProviderLease).where(
            ProviderLease.name == "overpass", ProviderLease.next_allowed_at <= now
        ).values(next_allowed_at=now + timedelta(seconds=max(interval, 1))))
        session.commit()
        if result.rowcount != 1:
            lease = session.get(ProviderLease, "overpass")
            remaining = math.ceil((as_utc(lease.next_allowed_at) - now).total_seconds())
            raise SourceBusy(max(remaining, 1))


def run_search(sessions, settings, source, city, segments, limit, use_cache=True):
    segments = sorted(set(segments))
    # Include endpoint identity so changing providers cannot reuse another provider's cache.
    identity = [source.name, getattr(source, "url", ""), city.ibge_code, segments, limit]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    now = utcnow()
    cached = False
    with sessions() as session:
        cache = session.get(SearchCache, key)
        if use_cache and cache and as_utc(cache.expires_at) > now:
            candidates = [Candidate(**item) for item in cache.payload["candidates"]]
            fetched_at = as_utc(cache.fetched_at)
            cached = True
    if not cached:
        if source.name == "openstreetmap":
            acquire_provider_slot(sessions, settings.provider_interval_seconds)
        candidates = source.search(city, segments, limit)
        fetched_at = utcnow()
    lead_ids, inserted, updated = [], 0, 0
    with sessions() as session:
        for candidate in candidates:
            # Only identifiers from the source determine duplicates. A shared
            # call-centre number must not merge different branches of a business.
            public_values = candidate.to_dict()
            public_values["priority"] = priority_for(candidate)
            public_values["last_seen_at"] = fetched_at
            statement = db_insert(session, Lead).values(id=new_id(), **public_values)
            inserted_id = session.execute(statement.on_conflict_do_nothing(
                index_elements=["source", "source_ref"]
            ).returning(Lead.id)).scalar_one_or_none()
            if inserted_id:
                inserted += 1
                lead_ids.append(inserted_id)
            else:
                existing = session.execute(select(Lead).where(
                    Lead.source == candidate.source, Lead.source_ref == candidate.source_ref
                ).with_for_update()).scalar_one()
                # Preserve consent, reviewer decisions and the approved recipient.
                # An existing analysis becomes stale only if public facts changed.
                changed = any(getattr(existing, field) != value for field, value in public_values.items()
                              if field not in {"last_seen_at", "priority"})
                for field, value in public_values.items():
                    setattr(existing, field, value)
                if changed:
                    existing.analysis = None
                updated += 1
                lead_ids.append(existing.id)
        if not cached:
            values = {"key": key, "payload": {"candidates": [c.to_dict() for c in candidates]},
                      "fetched_at": fetched_at, "expires_at": fetched_at + timedelta(hours=settings.cache_hours)}
            session.execute(db_insert(session, SearchCache).values(**values).on_conflict_do_update(
                index_elements=["key"], set_={k: v for k, v in values.items() if k != "key"}
            ))
        run = SearchRun(city=city.name, segments=segments, source=source.name, cached=cached,
                        found=len(candidates), inserted=inserted, updated=updated)
        session.add(run)
        session.commit()
        return {"busca_id": run.id, "cidade": city.name, "codigo_ibge": city.ibge_code,
                "segmentos": segments, "fonte": source.name, "atribuicao": source.attribution,
                "cache": cached, "dados_consultados_em": fetched_at.isoformat(),
                "encontradas": len(candidates), "novas": inserted, "ja_cadastradas": updated,
                "empresas_ids": lead_ids,
                "aviso": "Resultados são possíveis clientes, não contatos automaticamente autorizados. Telefone público não confirma uso de WhatsApp."}
