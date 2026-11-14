"""Provider SerpApi — Google Flights: ricerca LIVE con prezzi reali.

Usato per la ricerca on-demand della dashboard (molte proposte per data, con
orari e compagnie reali). Gli alert NON usano questo provider, per non consumare
la quota a pagamento: restano su Travelpayouts (Data API).

Docs: https://serpapi.com/google-flights-api
Auth: parametro query `api_key`. Prezzi nella valuta richiesta (`currency`).
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import FlightOffer, FlightProvider, Source

log = logging.getLogger("flynotify.serpapi")

# Google Flights (SerpApi) vuole codici AEROPORTO, non codici città. Qui mappiamo
# i principali codici città/metropolitani sui loro aeroporti: SerpApi accetta più
# aeroporti separati da virgola in UNA sola chiamata (nessun costo quota extra).
CITY_TO_AIRPORTS: dict[str, str] = {
    # --- Italia ---
    "MIL": "MXP,LIN,BGY",
    "ROM": "FCO,CIA",
    "VCE": "VCE,TSF",            # Venezia + Treviso
    "NAP": "NAP",
    "PMO": "PMO",
    "CTA": "CTA",
    "BLQ": "BLQ",
    "BRI": "BRI",
    "CAG": "CAG",
    "PSA": "PSA",
    "FLR": "FLR,PSA",            # Firenze (anche Pisa)
    "TRN": "TRN",
    "VRN": "VRN",
    "BGY": "BGY",
    "TRS": "TRS",
    "GOA": "GOA",
    "BDS": "BDS",
    "SUF": "SUF",
    "AHO": "AHO",
    "OLB": "OLB",
    # --- Europa (città multi-scalo) ---
    "LON": "LHR,LGW,STN,LTN,LCY",
    "PAR": "CDG,ORY,BVA",
    "BER": "BER",
    "MAD": "MAD",
    "BCN": "BCN",
    "MOW": "SVO,DME,VKO",
    "STO": "ARN,BMA,NYO",
    "OSL": "OSL,TRF",
    "BRU": "BRU,CRL",            # Bruxelles + Charleroi
    "FRA": "FRA,HHN",
    "HAM": "HAM",
    "DUS": "DUS,NRN,CGN",
    "MUC": "MUC",
    "VIE": "VIE",
    "ZRH": "ZRH",
    "GVA": "GVA",
    "AMS": "AMS,EIN",
    "CPH": "CPH",
    "DUB": "DUB",
    "LIS": "LIS",
    "OPO": "OPO",
    "ATH": "ATH",
    "IST": "IST,SAW",            # Istanbul + Sabiha
    "WAW": "WAW,WMI",
    "PRG": "PRG",
    "BUD": "BUD",
    # --- Resto del mondo ---
    "NYC": "JFK,EWR,LGA",
    "WAS": "IAD,DCA,BWI",
    "CHI": "ORD,MDW",
    "TYO": "HND,NRT",
    "OSA": "KIX,ITM",
    "SEL": "ICN,GMP",
    "BJS": "PEK,PKX",
    "SHA": "PVG,SHA",
    "BKK": "BKK,DMK",
    "DXB": "DXB,DWC",
    "SAO": "GRU,CGH,VCP",
    "RIO": "GIG,SDU",
    "BUE": "EZE,AEP",
}


def _expand(code: str) -> str:
    """Espande un codice città nei suoi aeroporti (CSV); altrimenti lo lascia invariato."""
    return CITY_TO_AIRPORTS.get(code.upper(), code)


class SerpApiFlightsClient(FlightProvider):
    name = "serpapi"

    @property
    def enabled(self) -> bool:
        return bool(settings.SERPAPI_KEY)

    def search_offers(self, origin, destination, depart_date, return_date=None,
                      adults=1, currency="EUR", exact_date=False,
                      months=None, max_offset_days=None) -> list[FlightOffer]:
        # SerpApi interroga sempre la data esatta: exact_date e i parametri di
        # finestra (months/max_offset_days) sono accettati per compatibilità con
        # l'interfaccia comune, ma ininfluenti qui.
        if not self.enabled:
            return []
        params = {
            "engine": "google_flights",
            "api_key": settings.SERPAPI_KEY,
            "departure_id": _expand(origin),
            "arrival_id": _expand(destination),
            "outbound_date": depart_date,
            "type": 1 if return_date else 2,   # 1=andata/ritorno, 2=solo andata
            "currency": currency.upper(),
            "hl": "it",
            "gl": "it",
            "adults": adults,
        }
        if return_date:
            params["return_date"] = return_date
        try:
            self.calls += 1
            with httpx.Client(base_url=settings.SERPAPI_BASE_URL,
                              timeout=settings.SERPAPI_TIMEOUT_SECONDS) as c:
                r = c.get("/search.json", params=params)
                r.raise_for_status()
                data = r.json()
            if data.get("error"):
                log.warning("SerpApi error: %s", data["error"])
                return []
            out: list[FlightOffer] = []
            itineraries = (data.get("best_flights") or []) + (data.get("other_flights") or [])
            for it in itineraries:
                price = float(it.get("price", 0) or 0)
                if price <= 0:
                    continue
                segs = it.get("flights") or []
                if not segs:
                    continue
                dep = segs[0].get("departure_airport") or {}
                arr = segs[-1].get("arrival_airport") or {}
                dep_time = dep.get("time")            # es. "2026-12-15 08:35"
                dep_date = (dep_time or depart_date)[:10]
                hhmm = dep_time[11:16] if (dep_time and len(dep_time) >= 16) else None
                carriers: list[str] = []
                for s in segs:
                    a = s.get("airline")
                    if a and a not in carriers:
                        carriers.append(a)
                out.append(FlightOffer(
                    origin=dep.get("id", origin),
                    destination=arr.get("id", destination),
                    depart_date=dep_date,
                    depart_time=hhmm,
                    return_date=return_date,
                    price=price,
                    currency=currency.upper(),
                    stops=len(it.get("layovers") or []),
                    carriers=carriers,
                    source=Source(provider=self.name,
                                  carrier=carriers[0] if carriers else None),
                ))
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("SerpApi google_flights error: %s", e)
            return []
