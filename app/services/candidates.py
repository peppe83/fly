"""Generatore di date candidate per gli alert.

Trasforma un alert (con giorni della settimana, orari, tipo viaggio e orizzonte)
nell'elenco delle coppie (partenza, ritorno) che il worker deve interrogare.

Casi d'uso coperti:
  - weekend scorrevoli nei prossimi N mesi (orizzonte): es. "Milano → ovunque,
    partenza Ven/Sab, ritorno Dom";
  - gite in giornata (same_day) nei prossimi N mesi, Sab o Dom;
  - finestra di date fissa (es. 27–30 agosto 2027), con o senza ritorno.
Ogni run usa `today` come riferimento, quindi l'orizzonte "scorre" da solo.
"""
from __future__ import annotations

from datetime import date, timedelta

# Limite di sicurezza alle coppie generate per alert (tutela la quota chiamate).
DEFAULT_CAP = 40


def _parse_dows(value: str | None, fallback_single: int | None) -> set[int]:
    """Legge i giorni ISO (1=Lun..7=Dom) dal CSV; in mancanza usa il singolo legacy."""
    if value:
        out = {int(p) for p in str(value).split(",")
               if p.strip().isdigit() and 1 <= int(p) <= 7}
        if out:
            return out
    if fallback_single:
        return {int(fallback_single)}
    return set()


def _mins(hhmm: str | None) -> int | None:
    if not hhmm or ":" not in hhmm:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def time_in_window(hhmm: str | None, lo: str | None, hi: str | None) -> bool:
    """True se l'orario rientra nella finestra [lo, hi].

    Se l'orario non è noto o la finestra non è impostata non si filtra (True),
    per non scartare offerte dalla fonte a catalogo quando il dato manca.
    """
    t = _mins(hhmm)
    if t is None:
        return True
    lom, him = _mins(lo), _mins(hi)
    if lom is not None and t < lom:
        return False
    if him is not None and t > him:
        return False
    return True


def _next_dow(start: date, dows: set[int], max_ahead: int = 7) -> date | None:
    """Prima data >= start il cui giorno ISO è in `dows` (entro max_ahead giorni)."""
    for i in range(max_ahead + 1):
        d = start + timedelta(days=i)
        if d.isoweekday() in dows:
            return d
    return None


def _build_return(alert, depart: date, trip: str,
                  return_dows: set[int], window_end: date) -> date | None:
    if trip == "one_way":
        return None
    if trip == "same_day":
        return depart
    # round_trip
    if return_dows:
        r = _next_dow(depart, return_dows, max_ahead=7)
        return r or depart
    if alert.return_from:
        return alert.return_from if alert.return_from >= depart else depart
    # Default weekend: due notti, senza sforare la finestra fissa.
    return min(depart + timedelta(days=2), window_end)


def candidate_pairs(alert, today: date | None = None,
                    cap: int = DEFAULT_CAP) -> list[tuple[date, date | None]]:
    today = today or date.today()
    trip = getattr(alert, "trip_type", None) or "round_trip"
    depart_dows = _parse_dows(getattr(alert, "depart_dows", None), alert.depart_dow)
    return_dows = _parse_dows(getattr(alert, "return_dows", None), alert.return_dow)

    horizon = getattr(alert, "horizon_months", None)
    if horizon:
        # Orizzonte scorrevole: da oggi (o dalla partenza se futura) a +N mesi.
        start = max(today, alert.depart_from) if alert.depart_from else today
        end = today + timedelta(days=int(horizon) * 30)
    else:
        # Finestra fissa.
        start = max(today, alert.depart_from)
        end = alert.depart_to or alert.depart_from

    if end < start:
        return []

    pairs: list[tuple[date, date | None]] = []
    d = start
    while d <= end and len(pairs) < cap:
        if not depart_dows or d.isoweekday() in depart_dows:
            pairs.append((d, _build_return(alert, d, trip, return_dows, end)))
        d += timedelta(days=1)
    return pairs
