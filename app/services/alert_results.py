"""Soluzioni salvate per alert (ultimo controllo) e loro presentazione."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AlertOffer, PriceHistory
from .places import place


def save_ranked(db: Session, alert_id: str, ranked) -> None:
    """Sostituisce le soluzioni salvate dell'alert con quelle dell'ultimo controllo.
    Non fa commit: lo fa il chiamante."""
    db.query(AlertOffer).filter(AlertOffer.alert_id == alert_id).delete()
    for i, o in enumerate(ranked, start=1):
        db.add(AlertOffer(alert_id=alert_id, rank=i, price=o.price,
                          offer_json=o.model_dump()))


def decorate(offer: dict) -> dict:
    """Aggiunge i nomi leggibili di origine e destinazione a un'offerta."""
    o = dict(offer)
    dest = place(o.get("destination"))
    org = place(o.get("origin"))
    o["destination_name"] = dest["label"]
    o["destination_city"] = dest["city"]
    o["origin_name"] = org["label"]
    return o


def load_offers(db: Session, alert_id: str) -> tuple[list[dict], str | None, bool]:
    """(offerte, quando, da_storico). Se l'alert non ha ancora una classifica
    salvata (creato prima di questa funzione) ripiega sulle ultime migliori
    offerte dello storico prezzi."""
    rows = (db.query(AlertOffer).filter(AlertOffer.alert_id == alert_id)
            .order_by(AlertOffer.rank).all())
    if rows:
        return ([decorate(r.offer_json) for r in rows],
                rows[0].observed_at.isoformat(), False)
    hist = (db.query(PriceHistory).filter(PriceHistory.alert_id == alert_id)
            .order_by(PriceHistory.observed_at.desc()).limit(40).all())
    seen, out = set(), []
    for h in hist:
        o = h.offer_json or {}
        key = (o.get("destination"), o.get("depart_date"), o.get("return_date"), o.get("price"))
        if key in seen:
            continue
        seen.add(key)
        out.append(decorate(o))
    out.sort(key=lambda o: o.get("price") or 0)
    return out, (hist[0].observed_at.isoformat() if hist else None), True
