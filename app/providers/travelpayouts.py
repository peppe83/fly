"""Provider Travelpayouts (Aviasales) Data API: gratuito, copertura low-cost.

Prezzi da catalogo (indicativi). Auth via query param `token` (+ `marker`).
Docs: https://support.travelpayouts.com/hc/en-us/categories/200358578
NB: gli endpoint della Data API possono variare; parsing difensivo con fallback.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from ..config import settings
from .base import DateDeal, DestinationDeal, FlightOffer, FlightProvider, Source

log = logging.getLogger("flynotify.travelpayouts")


def _parse_day(value: str | None) -> date | None:
    """YYYY-MM-DD -> date; None se il formato non è una data esatta."""
    if not value or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


class TravelpayoutsClient(FlightProvider):
    name = "travelpayouts"

    @property
    def enabled(self) -> bool:
        return bool(settings.TRAVELPAYOUTS_TOKEN)

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=settings.TRAVELPAYOUTS_BASE_URL, timeout=15)

    def _params(self, **kw) -> dict:
        base = {"token": settings.TRAVELPAYOUTS_TOKEN,
                "currency": settings.TRAVELPAYOUTS_CURRENCY}
        if settings.TRAVELPAYOUTS_MARKER:
            base["marker"] = settings.TRAVELPAYOUTS_MARKER
        base.update({k: v for k, v in kw.items() if v is not None})
        return base

    def search_offers(self, origin, destination, depart_date, return_date=None,
                      adults=1, currency="EUR", exact_date=False) -> list[FlightOffer]:
        if not self.enabled:
            return []
        # La fonte gratuita restituisce un solo prezzo (il più economico) per
        # data esatta. Per la DASHBOARD (exact_date=False) allarghiamo la singola
        # data all'intero mese e teniamo le partenze entro +/- MAX_DATE_OFFSET_DAYS:
        # così l'utente vede più alternative vicine. Per gli ALERT (exact_date=True)
        # interroghiamo la data esatta, per rispettare giorno della settimana e orari.
        exact = _parse_day(depart_date)
        if exact_date:
            query_depart = depart_date
            query_return = return_date
        else:
            query_depart = depart_date[:7] if exact else depart_date
            query_return = (return_date[:7] if (return_date and _parse_day(return_date))
                            else return_date)
        params = self._params(origin=origin, destination=destination,
                               departure_at=query_depart, return_at=query_return,
                               sorting="price", unique="false",
                               limit=(10 if exact_date else 50),
                               one_way=(return_date is None))
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/aviasales/v3/prices_for_dates", params=params)
                r.raise_for_status()
                out = []
                for d in r.json().get("data", []):
                    price = float(d.get("price", 0) or 0)
                    if price <= 0:
                        continue
                    dep = (d.get("departure_at") or depart_date)[:10]
                    if exact and not exact_date:
                        dd = _parse_day(dep)
                        if dd and abs((dd - exact).days) > settings.MAX_DATE_OFFSET_DAYS:
                            continue
                    if exact_date and dep != depart_date:
                        continue
                    out.append(self._offer(d, origin, destination, dep,
                                           return_date, currency))
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts prices_for_dates error: %s", e)
            return []

    def offers_from_origin(self, origin, depart_date, return_date=None,
                           adults=1, currency="EUR", limit=30) -> list[FlightOffer]:
        """Voli più economici dall'origine verso QUALSIASI meta per una data esatta
        (alert "ovunque"): prices_for_dates senza destination, unique=true = una
        proposta (la più economica) per destinazione."""
        if not self.enabled:
            return []
        # unique=false: più voli per destinazione (orari diversi) così i filtri
        # orari degli alert hanno più candidati tra cui trovare una corrispondenza.
        params = self._params(origin=origin, departure_at=depart_date,
                               return_at=return_date, sorting="price", unique="false",
                               limit=max(limit, 100), one_way=(return_date is None))
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/aviasales/v3/prices_for_dates", params=params)
                r.raise_for_status()
                out = []
                for d in r.json().get("data", []):
                    price = float(d.get("price", 0) or 0)
                    if price <= 0:
                        continue
                    dep = (d.get("departure_at") or depart_date)[:10]
                    if dep != depart_date:
                        continue
                    out.append(self._offer(d, origin, d.get("destination"), dep,
                                           return_date, currency))
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts offers_from_origin error: %s", e)
            return []

    def _offer(self, d: dict, origin, destination, dep, return_date, currency) -> FlightOffer:
        """Normalizza una riga prices_for_dates in FlightOffer, estraendo gli orari."""
        carrier = d.get("airline")
        dep_full = d.get("departure_at") or ""
        ret_full = d.get("return_at") or ""
        depart_time = dep_full[11:16] if len(dep_full) >= 16 else None
        return_time = ret_full[11:16] if len(ret_full) >= 16 else None
        return FlightOffer(
            origin=d.get("origin", origin),
            destination=d.get("destination", destination),
            depart_date=dep,
            return_date=(d.get("return_at") or return_date or None)[:10]
            if (d.get("return_at") or return_date) else None,
            price=float(d.get("price", 0) or 0), currency=currency.upper(),
            stops=d.get("transfers"),
            carriers=[carrier] if carrier else [],
            depart_time=depart_time, return_time=return_time,
            source=Source(provider=self.name, carrier=carrier),
        )

    def inspiration_search(self, origin, max_price=None, currency="EUR") -> list[DestinationDeal]:
        if not self.enabled:
            return []
        params = self._params(origin=origin, one_way="false", period_type="year",
                              sorting="price", limit=30, show_to_affiliates="true")
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/v2/prices/latest", params=params)
                r.raise_for_status()
                out = []
                for d in r.json().get("data", []):
                    price = float(d.get("value", 0) or 0)
                    if price <= 0 or (max_price and price > max_price):
                        continue
                    out.append(DestinationDeal(
                        origin=d.get("origin", origin), destination=d.get("destination"),
                        depart_date=d.get("depart_date"), return_date=d.get("return_date"),
                        price=price, currency=currency.upper(), indicative=True,
                        source=Source(provider=self.name),
                    ))
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts prices/latest error: %s", e)
            return []

    def cheapest_dates(self, origin, destination, currency="EUR") -> list[DateDeal]:
        if not self.enabled:
            return []
        params = self._params(origin=origin, destination=destination,
                              calendar_type="departure_date")
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/v1/prices/calendar", params=params)
                r.raise_for_status()
                data = r.json().get("data", {})
                out = []
                for dep_date, info in data.items():
                    price = float(info.get("price", 0) or 0)
                    if price <= 0:
                        continue
                    out.append(DateDeal(
                        origin=origin, destination=destination,
                        depart_date=dep_date, return_date=info.get("return_at"),
                        price=price, currency=currency.upper(),
                        source=Source(provider=self.name),
                    ))
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts prices/calendar error: %s", e)
            return []
