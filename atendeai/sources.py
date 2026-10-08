from dataclasses import asdict, dataclass
import json
import re
from urllib.parse import urlsplit

import httpx

from .catalog import City, SEGMENTS, normalized, segment_from_tags


OSM_ATTRIBUTION = "© OpenStreetMap contributors — ODbL 1.0"
OSM_LICENSE = "https://opendatacommons.org/licenses/odbl/1-0/"


class SourceError(Exception):
    pass


class SourceBusy(SourceError):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("A fonte de pesquisa está em intervalo de espera. Tente novamente depois.")


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    # Do not join multiple published numbers into one fabricated number.
    if ";" in value or "/" in value or "," in value:
        return None
    digits = re.sub(r"\D", "", value)
    if value.lstrip().startswith("+"):
        national = digits[2:] if digits.startswith("55") else ""
    elif len(digits) in {10, 11}:
        national = digits
    elif len(digits) in {12, 13} and digits.startswith("55"):
        national = digits[2:]
    else:
        return None
    if len(national) not in {10, 11} or national[0] == "0" or len(set(national)) < 3:
        return None
    return "+55" + national


def safe_website(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            return None
        return value[:2000]
    except ValueError:
        return None


@dataclass
class Candidate:
    name: str
    city: str
    city_ibge: str
    segment: str
    source: str
    source_ref: str
    source_url: str
    source_license: str
    is_demo: bool = False
    address: str | None = None
    phone_public: str | None = None
    phone_normalized: str | None = None
    website: str | None = None
    email_public: str | None = None
    opening_hours: str | None = None

    def to_dict(self):
        return asdict(self)


def build_query(city: City, segments: list[str], limit: int) -> str:
    selectors = sorted({pair for name in segments for pair in SEGMENTS[name]["selectors"]})
    lines = [f'nwr(area.city)["{key}"~"^({values})$"]["name"];' for key, values in selectors]
    return (
        '[out:json][timeout:25];\n'
        'area["ISO3166-2"="BR-SP"]["admin_level"="4"]->.sp;\n'
        f'rel(area.sp)["boundary"="administrative"]["admin_level"="8"]'
        f'["IBGE:GEOCODIGO"={json.dumps(city.ibge_code)}]->.municipality;\n'
        '.municipality map_to_area->.city;\n(\n' + '\n'.join(lines) +
        f'\n);\nout center tags {limit};'
    )


def parse_elements(data: dict, city: City, segments: list[str], limit: int) -> list[Candidate]:
    if "elements" not in data or not isinstance(data["elements"], list):
        raise SourceError("A fonte devolveu uma resposta inválida.")
    # A partial Overpass response with a runtime error is not a successful search.
    if data.get("remark"):
        raise SourceError("A fonte não conseguiu concluir a busca. Tente novamente mais tarde.")
    found = []
    seen = set()
    for element in data["elements"]:
        tags = element.get("tags", {})
        kind, element_id = element.get("type"), element.get("id")
        if kind not in {"node", "way", "relation"} or not isinstance(element_id, int):
            continue
        if not tags.get("name") or tags.get("disused") == "yes" or tags.get("abandoned") == "yes":
            continue
        # Municipal-area filtering is the primary verification. Explicit address
        # contradictions are rejected rather than overwritten with the desired city.
        if tags.get("addr:state") and normalized(tags["addr:state"]) not in {"sp", "sao paulo"}:
            continue
        if tags.get("addr:city") and normalized(tags["addr:city"]) != normalized(city.name):
            continue
        if tags.get("addr:country") and normalized(tags["addr:country"]) not in {"br", "brasil", "brazil"}:
            continue
        segment = segment_from_tags(tags, segments)
        reference = f"{kind}:{element_id}"
        if not segment or reference in seen:
            continue
        seen.add(reference)
        phone = tags.get("contact:phone") or tags.get("phone")
        address = ", ".join(str(tags[key]) for key in ["addr:street", "addr:housenumber", "addr:suburb", "addr:postcode"] if tags.get(key)) or None
        found.append(Candidate(
            name=str(tags["name"])[:300], city=city.name, city_ibge=city.ibge_code,
            segment=segment, source="openstreetmap", source_ref=reference,
            source_url=f"https://www.openstreetmap.org/{kind}/{element_id}",
            source_license=OSM_LICENSE, address=address,
            phone_public=str(phone)[:250] if phone else None,
            phone_normalized=normalize_phone(phone),
            website=safe_website(tags.get("contact:website") or tags.get("website")),
            email_public=str(tags.get("contact:email") or tags.get("email") or "")[:300] or None,
            opening_hours=str(tags.get("opening_hours") or "")[:2000] or None,
        ))
        if len(found) >= limit:
            break
    return found


class OverpassSource:
    name = "openstreetmap"
    attribution = OSM_ATTRIBUTION

    def __init__(self, url: str, transport=None):
        self.url = url
        self.transport = transport

    def search(self, city: City, segments: list[str], limit: int):
        try:
            with httpx.Client(timeout=httpx.Timeout(35, connect=10), transport=self.transport,
                              headers={"User-Agent": "AtendeAI-SP-Pilot/0.1"}) as client:
                response = client.post(self.url, data={"data": build_query(city, segments, limit)})
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "60")
                    raise SourceBusy(int(retry) if retry.isdigit() else 60)
                response.raise_for_status()
                payload = response.json()
        except SourceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError("Não foi possível consultar a fonte de empresas. Nenhum resultado foi inventado.") from exc
        return parse_elements(payload, city, segments, limit)


class DemoSource:
    name = "demo"
    attribution = "Empresas fictícias, exclusivamente para testar o sistema."

    def search(self, city: City, segments: list[str], limit: int):
        # No phone numbers, emails or websites that could belong to real people.
        return [Candidate(
            name=f"Empresa de demonstração — {SEGMENTS[name]['label']}",
            city=city.name, city_ibge=city.ibge_code, segment=name,
            source="demo", source_ref=f"{city.ibge_code}:{name}",
            source_url="https://example.invalid/demonstracao",
            source_license="Dados fictícios para teste", is_demo=True,
        ) for name in segments][:limit]
