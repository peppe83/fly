"""SearchService: orchestratore multi-provider.

Interroga i provider abilitati, normalizza, UNISCE e DEDUPLICA tenendo il
prezzo minimo, ordina per prezzo. Nessuna cache persistente: solo cache di
esecuzione (RunCache) per non ripetere chiamate identiche nello stesso run.
"""
from __future__ import annotations

from ..providers.amadeus import AmadeusClient
from ..providers.base import DateDeal, DestinationDeal, FlightOffer
from ..providers.kiwi import KiwiClient
from ..providers.run_cache import RunCache
from ..providers.serpapi_flights import SerpApiFlightsClient
from ..providers.travelpayouts import TravelpayoutsClient


class SearchService:
    def __init__(self, run_cache: RunCache | None = None) -> None:
        # Fonti a catalogo (free): usate dagli alert e come fallback.
        self.providers = [TravelpayoutsClient(), AmadeusClient()]
        # Fonti LIVE (a pagamento/quota): usate solo per la ricerca on-demand
        # della dashboard, mai dagli alert. Più fonti = più offerte reali.
        self.live_providers = [SerpApiFlightsClient(), KiwiClient()]
        self.cache = run_cache or RunCache()
        self.last_providers: list[str] = []   # fonti effettivamente usate nell'ultima ricerca

    @property
    def enabled_providers(self):
        return [p for p in self.providers if p.enabled]

    @property
    def enabled_live_providers(self):
        return [p for p in self.live_providers if p.enabled]

    def providers_for(self, include_live: bool):
        """Fonti da usare: live per la dashboard (se configurate), altrimenti catalogo."""
        if include_live and self.enabled_live_providers:
            return self.enabled_live_providers
        return self.enabled_providers

    @property
    def total_calls(self) -> int:
        return sum(p.calls for p in self.providers)

    # -- ricerche ---------------------------------------------------------
    def _query(self, providers, origin, destination, depart_date, return_date,
               adults, currency, exact_date=False, months=None,
               max_offset_days=None) -> list[FlightOffer]:
        out: list[FlightOffer] = []
        for p in providers:
            key = (f"offers:{p.name}:{origin}:{destination}:{depart_date}:"
                   f"{return_date}:{adults}:{currency}:{exact_date}:{months}:{max_offset_days}")
            out += self.cache.get_or_call(
                key, lambda p=p: p.search_offers(origin, destination, depart_date,
                                                 return_date, adults, currency, exact_date,
                                                 months, max_offset_days))
        return out

    def search_offers(self, origin, destination, depart_date, return_date=None,
                      adults=1, currency="EUR", include_live=False,
                      exact_date=False, months=None,
                      max_offset_days=None) -> list[FlightOffer]:
        # Dashboard: interroga TUTTE le fonti live (SerpApi + Kiwi) E il catalogo
        # (Travelpayouts), poi unisce: così si vedono il più possibile le offerte.
        # Gli alert (include_live=False) usano sempre e solo il catalogo.
        live = self.enabled_live_providers if include_live else []
        results = self._query(live, origin, destination, depart_date, return_date,
                              adults, currency, exact_date, months, max_offset_days)
        catalog = self._query(self.enabled_providers, origin, destination,
                              depart_date, return_date, adults, currency,
                              exact_date, months, max_offset_days)
        used = [p.name for p in live] if results else []
        used += [p.name for p in self.enabled_providers]
        self.last_providers = used
        return self._dedup_offers(results + catalog)

    def anywhere_offers_for_date(self, origin, depart_date, return_date=None,
                                 adults=1, currency="EUR") -> list[FlightOffer]:
        """Alert "ovunque": voli più economici dall'origine verso qualsiasi meta
        per una data esatta. Solo catalogo (Travelpayouts)."""
        out: list[FlightOffer] = []
        for p in self.enabled_providers:
            key = f"anyoffers:{p.name}:{origin}:{depart_date}:{return_date}:{currency}"
            out += self.cache.get_or_call(
                key, lambda p=p: p.offers_from_origin(origin, depart_date,
                                                      return_date, adults, currency))
        return self._dedup_offers(out)

    def explore(self, origin, max_price=None, currency="EUR",
                live_top_n: int = 0) -> list[DestinationDeal]:
        # Scoperta "ovunque": solo Travelpayouts (SerpApi non supporta "ovunque").
        results: list[DestinationDeal] = []
        for p in self.enabled_providers:
            key = f"insp:{p.name}:{origin}:{max_price}:{currency}"
            results += self.cache.get_or_call(
                key, lambda p=p: p.inspiration_search(origin, max_price, currency))
        # Kiwi supporta "ovunque" nativamente con PREZZI REALI: le sue mete
        # entrano subito come non-indicative e hanno priorità nel dedup.
        for p in self.enabled_live_providers:
            key = f"anyexpl:{p.name}:{origin}:{max_price}:{currency}"
            results += self.cache.get_or_call(
                key, lambda p=p: p.explore_anywhere(origin, max_price, currency))

        deals = self._dedup_destinations(results)
        # Ibrido: riprezza LIVE (SerpApi) le prime N mete più economiche ancora
        # indicative, così il prezzo mostrato è reale e non più solo indicativo.
        live = [p for p in self.enabled_live_providers if p.name == "serpapi"]
        if live_top_n and live:
            lp = live[0]
            for d in deals[:live_top_n]:
                if not d.depart_date:
                    continue
                offers = lp.search_offers(origin, d.destination, d.depart_date,
                                          d.return_date, 1, currency)
                if offers:
                    best = min(offers, key=lambda o: o.price)
                    d.price = best.price
                    d.currency = best.currency
                    d.indicative = False
                    d.source = best.source
        # Prima le mete con prezzo reale verificato (indicative=False), poi le
        # indicative; dentro ogni gruppo per prezzo crescente.
        return sorted(deals, key=lambda d: (d.indicative, d.price))

    def cheapest_dates(self, origin, destination, currency="EUR") -> list[DateDeal]:
        results: list[DateDeal] = []
        for p in self.enabled_providers:
            key = f"dates:{p.name}:{origin}:{destination}:{currency}"
            results += self.cache.get_or_call(
                key, lambda p=p: p.cheapest_dates(origin, destination, currency))
        return sorted(results, key=lambda d: d.price)

    # -- merge/dedup ------------------------------------------------------
    @staticmethod
    def _dedup_offers(offers: list[FlightOffer]) -> list[FlightOffer]:
        best: dict[str, FlightOffer] = {}
        for o in offers:
            cur = best.get(o.dedupe_key)
            if cur is None or o.price < cur.price:
                best[o.dedupe_key] = o
        return sorted(best.values(), key=lambda o: o.price)

    @staticmethod
    def _dedup_destinations(deals: list[DestinationDeal]) -> list[DestinationDeal]:
        best: dict[str, DestinationDeal] = {}
        for d in deals:
            if not d.destination:
                continue
            cur = best.get(d.destination)
            # Un prezzo reale (indicative=False) batte sempre un indicativo; a
            # parità di tipo vince il più economico.
            if (cur is None
                    or (not d.indicative and cur.indicative)
                    or (d.indicative == cur.indicative and d.price < cur.price)):
                best[d.destination] = d
        return sorted(best.values(), key=lambda d: (d.indicative, d.price))

    # -- helper per il worker --------------------------------------------
    def _passes_filters(self, alert, o: FlightOffer) -> bool:
        from .candidates import time_in_window
        if not time_in_window(o.depart_time, alert.depart_time_from, alert.depart_time_to):
            return False
        if not time_in_window(o.return_time, getattr(alert, "return_time_from", None),
                              getattr(alert, "return_time_to", None)):
            return False
        if alert.max_stops is not None and o.stops is not None and o.stops > alert.max_stops:
            return False
        return True

    def best_offer_for_alert(self, alert) -> FlightOffer | None:
        """Offerta migliore (prezzo minimo) per un alert.

        Scandisce le date candidate (weekend scorrevoli, giorni/orari ammessi,
        tipo viaggio, finestre fisse), applica i filtri e tiene il prezzo minimo.
        Gli alert usano SOLO il catalogo (Travelpayouts): mai la quota live.
        """
        from .candidates import candidate_pairs

        from ..config import settings
        currency = alert.currency or "EUR"
        is_any = alert.destination == "ANY"
        cap = (settings.ALERT_MAX_ANY_CANDIDATES if is_any
               else settings.ALERT_MAX_CANDIDATES)
        pairs = candidate_pairs(alert, cap=cap)
        if not pairs:
            pairs = [(alert.depart_from, alert.return_from)]

        best: FlightOffer | None = None
        for depart, ret in pairs:
            dep_s = depart.isoformat()
            ret_s = ret.isoformat() if ret else None
            if is_any:
                offers = self.anywhere_offers_for_date(alert.origin, dep_s, ret_s,
                                                       alert.adults, currency)
            else:
                offers = self.search_offers(alert.origin, alert.destination, dep_s,
                                            ret_s, alert.adults, currency,
                                            include_live=False, exact_date=True)
            for o in offers:
                if not self._passes_filters(alert, o):
                    continue
                if best is None or o.price < best.price:
                    best = o
        return best
