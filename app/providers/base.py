"""Modelli di dominio normalizzati e interfaccia comune dei provider voli."""
from __future__ import annotations

from abc import ABC
from typing import Optional

from pydantic import BaseModel


class Source(BaseModel):
    provider: str                     # 'amadeus' | 'travelpayouts'
    carrier: Optional[str] = None     # compagnia (validating carrier)


class FlightOffer(BaseModel):
    origin: str
    destination: str
    depart_date: str
    return_date: Optional[str] = None
    price: float
    currency: str = "EUR"
    stops: Optional[int] = None
    duration: Optional[str] = None
    carriers: list[str] = []
    depart_time: Optional[str] = None   # orario partenza (HH:MM)
    arrival_time: Optional[str] = None  # orario arrivo a destinazione (HH:MM)
    return_time: Optional[str] = None   # orario partenza del ritorno (HH:MM)
    source: Source

    @property
    def dedupe_key(self) -> str:
        base = f"{self.origin}-{self.destination}-{self.depart_date}-{self.return_date}"
        # Le fonti live (SerpApi) restituiscono più voli per la stessa data/tratta:
        # con l'orario li teniamo distinti; le fonti a catalogo (1/data) restano invariate.
        if self.depart_time:
            carrier = self.carriers[0] if self.carriers else ""
            return f"{base}-{self.depart_time}-{carrier}-{self.price}"
        return base


class DestinationDeal(BaseModel):
    origin: str
    destination: str
    depart_date: Optional[str] = None
    return_date: Optional[str] = None
    price: float
    currency: str = "EUR"
    indicative: bool = True
    source: Source


class DateDeal(BaseModel):
    origin: str
    destination: str
    depart_date: str
    return_date: Optional[str] = None
    price: float
    currency: str = "EUR"
    source: Source


class FlightProvider(ABC):
    """Interfaccia comune. Ogni implementazione deve essere resiliente:
    in caso di credenziali mancanti o errori di rete restituisce liste vuote."""

    name: str = "base"

    def __init__(self) -> None:
        self.calls: int = 0  # contatore chiamate effettuate (per quota/log)

    @property
    def enabled(self) -> bool:
        return False

    def search_offers(self, origin: str, destination: str, depart_date: str,
                      return_date: str | None = None, adults: int = 1,
                      currency: str = "EUR", exact_date: bool = False,
                      months: int | None = None,
                      max_offset_days: int | None = None) -> list[FlightOffer]:
        """`months`/`max_offset_days`: ampiezza della finestra date per la dashboard
        (quante mensilità scandire e di quanti giorni allargarsi attorno alla data).
        I provider che interrogano solo la data esatta li ignorano."""
        return []

    def explore_anywhere(self, origin: str, max_price: float | None = None,
                         currency: str = "EUR", date_from: str | None = None,
                         date_to: str | None = None) -> list[DestinationDeal]:
        """Mete più economiche dall'origine con PREZZI REALI (fonti live che
        supportano "ovunque", es. Kiwi). Default: nessun risultato."""
        return []

    def offers_from_origin(self, origin: str, depart_date: str,
                           return_date: str | None = None, adults: int = 1,
                           currency: str = "EUR", limit: int = 30) -> list[FlightOffer]:
        """Voli più economici dall'origine verso QUALSIASI destinazione per una
        data esatta (usato dagli alert "ovunque"). Default: nessun risultato."""
        return []

    def inspiration_search(self, origin: str, max_price: float | None = None,
                           currency: str = "EUR") -> list[DestinationDeal]:
        return []

    def cheapest_dates(self, origin: str, destination: str,
                       currency: str = "EUR") -> list[DateDeal]:
        return []
