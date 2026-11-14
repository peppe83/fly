"""Provider Kiwi.com (Tequila API): fonte LIVE con ottima copertura low-cost.

A differenza di SerpApi, Tequila accetta un RANGE di date e la ricerca "ovunque"
(senza destinazione) in una sola chiamata: ideale per scovare molte offerte.
Gli alert NON usano questo provider (resta tra le fonti live della dashboard).

Docs: https://tequila.kiwi.com/portal/docs/tequila_api/search_api
Auth: header `apikey`. Date nel formato dd/mm/yyyy. Prezzi nella valuta `curr`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import httpx

from ..config import settings
from .base import DestinationDeal, FlightOffer, FlightProvider, Source

log = logging.getLogger("flynotify.kiwi")


def _parse_iso(value: str | None) -> date | None:
    if not value or len(value) < 10:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _clamp(d: date) -> date:
    """Mantiene la data in una finestra ragionevole: da oggi a +1 anno."""
    today = datetime.utcnow().date()
    hi = today + timedelta(days=365)
    return min(max(d, today), hi)


class KiwiClient(FlightProvider):
    name = "kiwi"

    @property
    def enabled(self) -> bool:
        return bool(settings.KIWI_API_KEY)

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=settings.KIWI_BASE_URL,
                            headers={"apikey": settings.KIWI_API_KEY},
                            timeout=settings.KIWI_TIMEOUT_SECONDS)

    def _window(self, depart_date, exact_date, max_offset_days):
        """Finestra di date (date_from, date_to) in dd/mm/yyyy attorno alla partenza."""
        day = _parse_iso(depart_date)
        if not day:
            today = datetime.utcnow().date()
            return _ddmmyyyy(today), _ddmmyyyy(today + timedelta(days=30))
        if exact_date:
            return _ddmmyyyy(day), _ddmmyyyy(day)
        off = max_offset_days if max_offset_days is not None else settings.MAX_DATE_OFFSET_DAYS
        return _ddmmyyyy(_clamp(day - timedelta(days=off))), _ddmmyyyy(_clamp(day + timedelta(days=off)))

    def _get(self, params: dict) -> list[dict]:
        try:
            self.calls += 1
            with self._client() as c:
                r = c.get("/v2/search", params=params)
                r.raise_for_status()
                return r.json().get("data", []) or []
        except Exception as e:  # noqa: BLE001
            log.warning("Kiwi search error: %s", e)
            return []

    def search_offers(self, origin, destination, depart_date, return_date=None,
                      adults=1, currency="EUR", exact_date=False,
                      months=None, max_offset_days=None) -> list[FlightOffer]:
        if not self.enabled:
            return []
        date_from, date_to = self._window(depart_date, exact_date, max_offset_days)
        params = {
            "fly_from": origin, "fly_to": destination,
            "date_from": date_from, "date_to": date_to,
            "adults": adults, "curr": currency.upper(),
            "sort": "price", "limit": settings.KIWI_SEARCH_LIMIT,
            "vehicle_type": "aircraft",
            "flight_type": "round" if return_date else "oneway",
        }
        if return_date:
            rf, rt = self._window(return_date, exact_date, max_offset_days)
            params["return_from"], params["return_to"] = rf, rt
        return [o for o in (self._offer(d, origin, destination, currency)
                            for d in self._get(params)) if o]

    def explore_anywhere(self, origin, max_price=None, currency="EUR",
                         date_from=None, date_to=None) -> list[DestinationDeal]:
        """Mete più economiche dall'origine con PREZZI REALI (fly_to omesso =
        ovunque; one_for_city = una proposta, la più economica, per città)."""
        if not self.enabled:
            return []
        today = datetime.utcnow().date()
        df = date_from or _ddmmyyyy(today + timedelta(days=7))
        dt = date_to or _ddmmyyyy(today + timedelta(days=90))
        params = {
            "fly_from": origin, "date_from": df, "date_to": dt,
            "curr": currency.upper(), "sort": "price",
            "limit": max(settings.EXPLORE_MAX_DESTINATIONS, 100),
            "one_for_city": 1, "vehicle_type": "aircraft", "flight_type": "oneway",
        }
        if max_price:
            params["price_to"] = int(max_price)
        out: list[DestinationDeal] = []
        for d in self._get(params):
            price = float(d.get("price", 0) or 0)
            if price <= 0:
                continue
            out.append(DestinationDeal(
                origin=d.get("cityCodeFrom") or d.get("flyFrom") or origin,
                destination=d.get("cityCodeTo") or d.get("flyTo"),
                depart_date=(d.get("local_departure") or "")[:10] or None,
                return_date=None,
                price=price, currency=currency.upper(), indicative=False,
                source=Source(provider=self.name,
                              carrier=(d.get("airlines") or [None])[0]),
            ))
        return out

    def _offer(self, d: dict, origin, destination, currency) -> FlightOffer | None:
        price = float(d.get("price", 0) or 0)
        if price <= 0:
            return None
        route = d.get("route") or []
        outbound = [s for s in route if not s.get("return")]
        inbound = [s for s in route if s.get("return")]
        dep_iso = (outbound[0].get("local_departure") if outbound
                   else d.get("local_departure")) or ""
        ret_iso = inbound[0].get("local_departure") if inbound else None
        carriers = d.get("airlines") or []
        return FlightOffer(
            origin=d.get("cityCodeFrom") or d.get("flyFrom") or origin,
            destination=d.get("cityCodeTo") or d.get("flyTo") or destination,
            depart_date=(dep_iso or "")[:10],
            depart_time=dep_iso[11:16] if len(dep_iso) >= 16 else None,
            return_date=(ret_iso or "")[:10] if ret_iso else None,
            return_time=ret_iso[11:16] if (ret_iso and len(ret_iso) >= 16) else None,
            price=price, currency=currency.upper(),
            stops=max(len(outbound) - 1, 0),
            carriers=carriers,
            source=Source(provider=self.name,
                          carrier=carriers[0] if carriers else None),
        )
