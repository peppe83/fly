"""Micro-migrazioni idempotenti (no Alembic).

Aggiunge le colonne mancanti alle tabelle esistenti, così un DB già creato
(es. MySQL sul VPS) si allinea al modello senza ricreare nulla. Sicuro da
richiamare a ogni avvio: se la colonna c'è già, non fa niente.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("flynotify.migrations")

# Colonne introdotte per il potenziamento del worker (DDL per MySQL e SQLite).
_ALERT_COLUMNS: dict[str, str] = {
    "trip_type": "VARCHAR(12) NOT NULL DEFAULT 'round_trip'",
    "horizon_months": "INTEGER NULL",
    "depart_dows": "VARCHAR(20) NULL",
    "return_dows": "VARCHAR(20) NULL",
    "return_time_from": "VARCHAR(5) NULL",
    "return_time_to": "VARCHAR(5) NULL",
}


def _existing_columns(engine: Engine, table: str) -> set[str]:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()  # tabella non ancora creata: ci penserà create_all
    return {c["name"] for c in insp.get_columns(table)}


def ensure_alert_columns(engine: Engine) -> None:
    have = _existing_columns(engine, "alerts")
    if not have:
        return
    missing = {k: v for k, v in _ALERT_COLUMNS.items() if k not in have}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE alerts ADD COLUMN {name} {ddl}"))
            log.info("Migrazione: aggiunta colonna alerts.%s", name)


_USER_COLUMNS: dict[str, str] = {
    "run_times": "VARCHAR(40) NULL",
}


def ensure_user_columns(engine: Engine) -> None:
    have = _existing_columns(engine, "users")
    if not have:
        return
    missing = {k: v for k, v in _USER_COLUMNS.items() if k not in have}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
            log.info("Migrazione: aggiunta colonna users.%s", name)


def run_migrations(engine: Engine) -> None:
    try:
        ensure_alert_columns(engine)
        ensure_user_columns(engine)
    except Exception as e:  # noqa: BLE001
        log.warning("Migrazioni non applicate: %s", e)
