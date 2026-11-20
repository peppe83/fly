"""Nomi delle compagnie aeree dal codice IATA, da app/data/airlines.json."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "data" / "airlines.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def airline_name(code: str | None) -> str:
    """Nome della compagnia ("Ryanair"); se il codice è sconosciuto resta il codice."""
    code = (code or "").strip().upper()
    return _load().get(code, code)


def airline_names(codes) -> list[str]:
    return [airline_name(c) for c in (codes or []) if c]
