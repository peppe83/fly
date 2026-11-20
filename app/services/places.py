"""Nomi leggibili per i codici IATA (città/aeroporti), da app/data/iata.json."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "data" / "iata.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"k": {}, "c": {}, "a": {}}


def place(code: str | None) -> dict:
    """Descrive un codice IATA: {code, city, airport, country, label}.

    `label` è la forma breve da mostrare ("Bucarest, Romania" oppure
    "Londra · Gatwick, Regno Unito"); se il codice è sconosciuto resta il codice.
    """
    code = (code or "").upper()
    data = _load()
    city = data["c"].get(code)
    apt = data["a"].get(code)
    city_name = airport = country_code = None
    if city:                                  # codice città (MIL, LON, NAP...)
        city_name, country_code = city[0], city[1]
    if apt and not city:                      # solo aeroporto (MXP, LGW, OTP...)
        airport = apt[0]
        parent = data["c"].get(apt[1])
        city_name = parent[0] if parent else None
        country_code = apt[2] or (parent[1] if parent else None)
    country = data["k"].get(country_code or "")
    if not (city_name or airport):
        return {"code": code, "city": None, "airport": None, "country": None, "label": code}
    head = city_name if not airport else (f"{city_name} · {airport}" if city_name else airport)
    return {"code": code, "city": city_name, "airport": airport, "country": country,
            "label": head + (f", {country}" if country else "")}
