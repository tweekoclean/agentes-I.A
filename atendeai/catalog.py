from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata


def normalized(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                             if not unicodedata.combining(c)).split())


@dataclass(frozen=True)
class City:
    name: str
    ibge_code: str
    region: str


_data = json.loads((Path(__file__).parent / "data" / "cities.json").read_text(encoding="utf-8"))
CITIES = {normalized(item["nome"]): City(item["nome"], item["codigo_ibge"], item["area"])
          for item in _data}

# Selectors are supplied by the application, never interpolated from free text.
SEGMENTS = {
    "restaurantes": {"label": "Restaurantes e cafés", "selectors": [("amenity", "restaurant|cafe|fast_food|food_court")]},
    "lojas": {"label": "Lojas e comércio", "selectors": [("shop", "supermarket|convenience|clothes|shoes|electronics|furniture|hardware|books|bakery|butcher|pet|florist|bicycle|department_store|mall")]},
    "oficinas": {"label": "Oficinas e serviços automotivos", "selectors": [("shop", "car_repair|car_parts|tyres|motorcycle_repair"), ("amenity", "car_wash")]},
    "beleza": {"label": "Salões e cuidados pessoais", "selectors": [("shop", "hairdresser|beauty|massage")]},
    "servicos": {"label": "Prestadores de serviços", "selectors": [("craft", "electrician|plumber|carpenter|painter|locksmith|photographer|computer_repair"), ("shop", "laundry|copyshop|tailor"), ("office", "accountant|estate_agent|company")]},
    "academias": {"label": "Academias", "selectors": [("leisure", "fitness_centre|sports_centre")]},
    "hospedagem": {"label": "Hotéis e pousadas", "selectors": [("tourism", "hotel|guest_house|hostel")]},
}


def resolve_city(value: str) -> City:
    key = normalized(value)
    if key not in CITIES:
        raise ValueError("Cidade fora do catálogo inicial de São Paulo capital e interior. Consulte /v1/cidades.")
    return CITIES[key]


def segment_from_tags(tags: dict, requested: list[str]) -> str | None:
    for name in requested:
        for key, options in SEGMENTS[name]["selectors"]:
            if tags.get(key) in options.split("|"):
                return name
    return None
