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


def _months_ahead(start_iso: str, n: int) -> list[str]:
    """['2026-11', '2026-12', ...] a partire dal mese di `start_iso` (YYYY-MM-DD|YYYY-MM)."""
    try:
        y, m = int(start_iso[:4]), int(start_iso[5:7])
    except (ValueError, IndexError):
        return [start_iso[:7]]
    out = []
    for _ in range(max(1, n)):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


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

    def _prices_for_dates(self, params: dict) -> list[dict]:
        """Chiamata grezza a prices_for_dates; righe o lista vuota su errore."""
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/aviasales/v3/prices_for_dates", params=params)
                r.raise_for_status()
                return r.json().get("data", []) or []
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts prices_for_dates error: %s", e)
            return []

    def search_offers(self, origin, destination, depart_date, return_date=None,
                      adults=1, currency="EUR", exact_date=False,
                      months=None, max_offset_days=None) -> list[FlightOffer]:
        if not self.enabled:
            return []
        exact = _parse_day(depart_date)

        # ALERT (exact_date=True): data esatta, una riga; rispetta giorno/orari.
        if exact_date:
            params = self._params(origin=origin, destination=destination,
                                   departure_at=depart_date, return_at=return_date,
                                   sorting="price", unique="false", limit=10,
                                   one_way=(return_date is None))
            out = []
            for d in self._prices_for_dates(params):
                price = float(d.get("price", 0) or 0)
                dep = (d.get("departure_at") or depart_date)[:10]
                if price <= 0 or dep != depart_date:
                    continue
                out.append(self._offer(d, origin, destination, dep, return_date, currency))
            return out

        # DASHBOARD (exact_date=False): per avere PIÙ risultati scandiamo più mesi
        # a partire da quello scelto e teniamo le partenze entro +/- offset giorni.
        offset = max_offset_days if max_offset_days is not None else settings.MAX_DATE_OFFSET_DAYS
        nmonths = months if months is not None else settings.CATALOG_SEARCH_MONTHS
        limit = settings.CATALOG_SEARCH_LIMIT
        ret_has_day = bool(return_date and _parse_day(return_date))
        months_dep = _months_ahead(depart_date, nmonths) if exact else [depart_date]
        months_ret = (_months_ahead(return_date, nmonths) if ret_has_day
                      else [return_date] * len(months_dep))

        out: list[FlightOffer] = []
        for i, qdep in enumerate(months_dep):
            qret = months_ret[i] if i < len(months_ret) else return_date
            params = self._params(origin=origin, destination=destination,
                                   departure_at=qdep, return_at=qret,
                                   sorting="price", unique="false", limit=limit,
                                   one_way=(return_date is None))
            for d in self._prices_for_dates(params):
                price = float(d.get("price", 0) or 0)
                if price <= 0:
                    continue
                dep = (d.get("departure_at") or depart_date)[:10]
                if exact and offset is not None:
                    dd = _parse_day(dep)
                    if dd and abs((dd - exact).days) > offset:
                        continue
                out.append(self._offer(d, origin, destination, dep, return_date, currency))
        return out

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
                              sorting="price", limit=settings.EXPLORE_MAX_DESTINATIONS,
                              show_to_affiliates="true")
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
        """Date più economiche per una tratta. Uniamo PIÙ fonti di catalogo
        (calendario, matrice mensile, prezzi 'cheap') tenendo per ogni giorno il
        prezzo minimo: così la pagina "Mese più economico" mostra molte più date."""
        if not self.enabled:
            return []
        best: dict[str, DateDeal] = {}

        def _add(dep_date, ret_at, price):
            if not dep_date or price <= 0:
                return
            cur = best.get(dep_date)
            if cur is None or price < cur.price:
                best[dep_date] = DateDeal(
                    origin=origin, destination=destination,
                    depart_date=dep_date, return_date=ret_at,
                    price=price, currency=currency.upper(),
                    source=Source(provider=self.name))

        # 1) Calendario (una riga per giorno disponibile).
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/v1/prices/calendar", params=self._params(
                    origin=origin, destination=destination,
                    calendar_type="departure_date"))
                r.raise_for_status()
                for dep_date, info in (r.json().get("data", {}) or {}).items():
                    _add(dep_date, info.get("return_at"), float(info.get("price", 0) or 0))
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts prices/calendar error: %s", e)

        # 2) Matrice mensile: tutti i giorni dei prossimi mesi in una chiamata ciascuno.
        for month in _months_ahead(datetime.utcnow().strftime("%Y-%m-%d"),
                                    settings.CATALOG_SEARCH_MONTHS):
            try:
                with self._client() as c:
                    self.calls += 1
                    r = c.get("/v2/prices/month-matrix", params=self._params(
                        origin=origin, destination=destination,
                        month=f"{month}-01", show_to_affiliates="true"))
                    r.raise_for_status()
                    for d in (r.json().get("data", []) or []):
                        dep = (d.get("depart_date") or "")[:10]
                        _add(dep, d.get("return_date"), float(d.get("value", 0) or 0))
            except Exception as e:  # noqa: BLE001
                log.warning("Travelpayouts month-matrix error: %s", e)

        # 3) Prezzi "cheap": il più economico per mese (diretti e con scalo).
        try:
            with self._client() as c:
                self.calls += 1
                r = c.get("/v1/prices/cheap", params=self._params(
                    origin=origin, destination=destination))
                r.raise_for_status()
                for _dest, variants in (r.json().get("data", {}) or {}).items():
                    for info in (variants or {}).values():
                        dep = (info.get("departure_at") or "")[:10]
                        _add(dep, info.get("return_at"), float(info.get("price", 0) or 0))
        except Exception as e:  # noqa: BLE001
            log.warning("Travelpayouts prices/cheap error: %s", e)

        return sorted(best.values(), key=lambda d: d.depart_date)
