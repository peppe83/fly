"""Orari di esecuzione degli alert scelti dall'utente.

Ogni utente sceglie a che ora (fuso orario dell'utente) il worker deve controllare
i suoi alert: 1 orario al giorno per gli utenti, fino a 4 per admin/superadmin.
Il worker gira ogni ALERT_TIME_STEP_MINUTES (task di Windows): un orario scatta al
primo giro successivo, quindi gli orari ammessi sono multipli di quel passo.

Un utente SENZA orari scelti (run_times NULL) resta sul vecchio comportamento
a intervallo (poll_interval_hours): nulla cambia finché non sceglie.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import settings

log = logging.getLogger("flynotify.schedule")

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def max_runs_for(role: str | None) -> int:
    """Quanti orari al giorno può avere un utente, in base al ruolo."""
    return settings.ALERT_RUNS_ADMIN if role in ("admin", "superadmin") else settings.ALERT_RUNS_USER


def tz_of(name: str | None):
    try:
        return ZoneInfo(name or settings.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        log.warning("Fuso orario '%s' non valido: uso UTC", name)
        return timezone.utc


def parse_times(csv: str | None) -> list[str]:
    """CSV 'HH:MM,HH:MM' -> lista ordinata e senza doppioni (ignora i valori non validi)."""
    if not csv:
        return []
    out = {p.strip() for p in str(csv).split(",") if _HHMM.match(p.strip())}
    return sorted(out)


def validate_times(values: list[str], role: str | None) -> list[str]:
    """Normalizza e valida gli orari scelti; ValueError con messaggio in italiano."""
    cleaned = [str(v).strip() for v in (values or []) if str(v).strip()]
    for v in cleaned:
        if not _HHMM.match(v):
            raise ValueError(f"Orario non valido: {v}")
        minutes = int(v[:2]) * 60 + int(v[3:])
        if minutes % settings.ALERT_TIME_STEP_MINUTES:
            raise ValueError(
                f"{v}: gli orari devono essere multipli di {settings.ALERT_TIME_STEP_MINUTES} minuti")
    unique = sorted(set(cleaned))
    if len(unique) != len(cleaned):
        raise ValueError("Ci sono orari ripetuti")
    if not unique:
        raise ValueError("Scegli almeno un orario")
    limit = max_runs_for(role)
    if len(unique) > limit:
        raise ValueError(
            "Puoi scegliere un solo orario al giorno" if limit == 1
            else f"Puoi scegliere al massimo {limit} orari al giorno")
    return unique


def _slot_utc(day: date, hhmm: str, tz) -> datetime:
    """Istante (UTC naive) in cui scatta l'orario `hhmm` del giorno locale `day`."""
    local = datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[3:]), tzinfo=tz)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def is_due(user, now: datetime) -> bool:
    """True se il worker deve elaborare l'utente adesso (`now` = UTC naive)."""
    times = parse_times(getattr(user, "run_times", None))
    if not times:  # nessun orario scelto: vecchio comportamento a intervallo
        if user.last_run_at is None:
            return True
        return now - user.last_run_at >= timedelta(hours=user.poll_interval_hours)

    if user.last_run_at is None:
        return True
    tz = tz_of(user.timezone)
    today = now.replace(tzinfo=timezone.utc).astimezone(tz).date()
    # Basta guardare ieri e oggi: un orario passato dopo l'ultimo giro è "dovuto".
    # (Se il worker è stato fermo, recupera con UN solo giro, non uno per orario.)
    for day in (today - timedelta(days=1), today):
        for t in times:
            if user.last_run_at < _slot_utc(day, t, tz) <= now:
                return True
    return False


def next_run_local(user, now: datetime) -> datetime | None:
    """Prossimo orario previsto, nel fuso dell'utente (naive); None se a intervallo."""
    times = parse_times(getattr(user, "run_times", None))
    if not times:
        return None
    tz = tz_of(user.timezone)
    today = now.replace(tzinfo=timezone.utc).astimezone(tz).date()
    for offset in (0, 1):
        day = today + timedelta(days=offset)
        for t in times:
            if _slot_utc(day, t, tz) > now:
                return datetime(day.year, day.month, day.day, int(t[:2]), int(t[3:]))
    return None


def _to_local_iso(dt_utc: datetime | None, tz) -> str | None:
    if dt_utc is None:
        return None
    return (dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)
            .strftime("%Y-%m-%dT%H:%M"))


def schedule_info(user, now: datetime | None = None) -> dict:
    """Stato della pianificazione per l'API/UI."""
    now = now or datetime.utcnow()
    tz = tz_of(user.timezone)
    times = parse_times(user.run_times)
    nxt = next_run_local(user, now)
    return {
        "mode": "fixed" if times else "interval",
        "run_times": times,
        "max_runs": max_runs_for(user.role),
        "step_minutes": settings.ALERT_TIME_STEP_MINUTES,
        "timezone": user.timezone,
        "poll_interval_hours": user.poll_interval_hours,
        "next_run_local": nxt.strftime("%Y-%m-%dT%H:%M") if nxt else None,
        "last_run_local": _to_local_iso(user.last_run_at, tz),
    }
