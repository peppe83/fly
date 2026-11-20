"""Soluzioni salvate per alert (ultimo controllo) e loro presentazione."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AlertOffer, PriceHistory
from .airlines import airline_names
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
    o["carrier_names"] = airline_names(o.get("carriers"))
    return o


_DOW = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]


def _day(iso: str | None) -> str:
    """AAAA-MM-GG -> 'Sab 30-01-2027'."""
    if not iso or len(iso) < 10:
        return ""
    from datetime import date
    try:
        d = date(int(iso[:4]), int(iso[5:7]), int(iso[8:10]))
    except ValueError:
        return iso
    return f"{_DOW[d.weekday()]} {iso[8:10]}-{iso[5:7]}-{iso[:4]}"


def _times(a: str | None, b: str | None) -> str:
    return " → ".join(x for x in (a, b) if x)


def offer_summary(offer: dict) -> dict:
    """Testi pronti per la email: tratta con nomi, andata/ritorno con orari, dettagli."""
    o = decorate(offer)
    out = " · ".join(x for x in (_day(o.get("depart_date")),
                                 _times(o.get("depart_time"), o.get("arrival_time"))) if x)
    ret = ""
    if o.get("return_date"):
        ret = " · ".join(x for x in (_day(o.get("return_date")),
                                     _times(o.get("return_time"), o.get("return_arrival_time"))) if x)
    stops = o.get("stops")
    meta = []
    if stops is not None:
        meta.append("diretto" if stops == 0 else f"{stops} scal{'o' if stops == 1 else 'i'}")
    if o.get("carrier_names"):
        meta.append(", ".join(o["carrier_names"]))
    return {"route": f"{o['origin_name']} → {o['destination_name']}",
            "outbound": out, "ret": ret, "meta": " · ".join(meta)}


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


def alert_title(alert) -> str:
    """'Milano, Italia → Ovunque' / 'Palermo, Italia → Milano, Italia'."""
    dest = "Ovunque 🌍" if alert.destination == "ANY" else place(alert.destination)["label"]
    return f"{place(alert.origin)['label']} → {dest}"
