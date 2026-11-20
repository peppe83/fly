"""Alert Engine: decide quali soluzioni di un alert vanno comunicate.

Regola unica (la "soglia" è facoltativa):
  - con prezzo soglia (target_price): si comunicano le soluzioni <= soglia;
  - senza soglia: si comunicano TUTTE le soluzioni trovate nel controllo.
Nessun anti-ripetizione: se l'elenco c'è, viene comunicato a OGNI controllo.
"""
from __future__ import annotations

import hashlib
import uuid


def qualifying_offers(alert, ranked: list) -> list:
    """Le soluzioni da comunicare (ranked è già ordinato dalla più economica)."""
    if alert.target_price is None:
        return list(ranked)
    target = float(alert.target_price)
    return [o for o in ranked if float(o.price) <= target]


def reason_for(alert) -> str:
    return "below_target" if alert.target_price is not None else "all_results"


def build_notification_key(alert_id: str) -> str:
    """Chiave univoca per ogni invio (la tabella notifications è il registro degli avvisi)."""
    return hashlib.sha256(f"{alert_id}|{uuid.uuid4()}".encode()).hexdigest()
