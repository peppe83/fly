"""Worker schedulato (lanciato da Windows Task Scheduler).

Per OGNI utente attivo "dovuto" (è passato un suo orario di esecuzione scelto nella
pagina Alert, oppure — se non ne ha scelti — è scaduto il suo intervallo personale):
  - valuta i suoi alert ATTIVI (quelli sospesi vengono saltati);
  - registra lo storico prezzi e, se scatta un avviso, lo accumula;
  - invia UNA email riepilogativa (digest) con tutti gli avvisi dell'utente;
  - aggiorna last_run_at dell'utente.
Nessuna cache persistente: ogni run fa chiamate fresche.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .config import settings
from .db import SessionLocal, engine
from .models import Alert, EmailLog, Notification, PriceHistory, RunLog, User
from .providers.run_cache import RunCache
from .services import email as email_svc
from .services.alert_engine import build_notification_key, qualifying_offers, reason_for
from .services.alert_results import alert_title, offer_summary, save_ranked
from .services.schedule import is_due
from .services.search import SearchService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("flynotify.worker")

def run_worker() -> None:
    if not settings.ENABLE_ALERTS:
        log.info("ENABLE_ALERTS=false: worker non attivo.")
        return

    db = SessionLocal()
    rl = RunLog(status="ok")
    db.add(rl)
    db.commit()
    db.refresh(rl)

    now = datetime.utcnow()
    users_checked = alerts_checked = emails_sent = api_calls = 0

    try:
        users = db.query(User).filter(User.status == "active").all()
        for user in users:
            if not is_due(user, now):
                continue
            users_checked += 1
            svc = SearchService(RunCache())      # cache di esecuzione per-utente
            triggered: list[dict] = []

            alerts = db.query(Alert).filter(
                Alert.user_id == user.id, Alert.status == "active").all()
            for alert in alerts:
                alerts_checked += 1
                alert.last_checked = datetime.utcnow()
                try:
                    ranked = svc.ranked_offers_for_alert(alert)
                except Exception as e:  # noqa: BLE001
                    log.warning("Ricerca fallita alert %s: %s", alert.id, e)
                    ranked = []
                best = ranked[0] if ranked else None
                if not best:
                    continue
                save_ranked(db, alert.id, ranked)   # soluzioni mostrate nel dettaglio

                alert.last_price = best.price
                db.add(PriceHistory(alert_id=alert.id, price=best.price,
                                    currency=best.currency, offer_json=best.model_dump()))

                # Soluzioni da comunicare: <= soglia se impostata, altrimenti tutte.
                matching = qualifying_offers(alert, ranked)
                if not matching:
                    continue
                db.add(Notification(alert_id=alert.id, price=matching[0].price,
                                    reason=reason_for(alert),
                                    dedupe_key=build_notification_key(alert.id)))

                triggered.append({
                    "title": alert_title(alert),
                    "reason": reason_for(alert),
                    "threshold": float(alert.target_price) if alert.target_price is not None else None,
                    "currency": alert.currency,
                    "offers": [{**offer_summary(o.model_dump()), "price": float(o.price),
                                "currency": o.currency, "source": o.source.provider}
                               for o in matching],
                })

            # UNA email riepilogativa per utente
            if triggered:
                html = email_svc.build_digest_html(
                    user.full_name, triggered)
                n_off = sum(len(t["offers"]) for t in triggered)
                subject = (f"✈️ flynotify — {n_off} "
                           f"{'soluzione' if n_off == 1 else 'soluzioni'} per i tuoi alert")
                sent, err = email_svc.send_email(user.email, subject, html)
                db.add(EmailLog(user_id=user.id, to_email=user.email, subject=subject,
                                status="sent" if sent else "error", error_text=err))
                if sent:
                    emails_sent += 1

            user.last_run_at = datetime.utcnow()
            api_calls += svc.total_calls
            db.commit()

        rl.status = "ok"
    except Exception as e:  # noqa: BLE001
        db.rollback()
        rl.status = "error"
        rl.error_text = str(e)
        log.exception("Worker error")
    finally:
        rl.finished_at = datetime.utcnow()
        rl.users_checked = users_checked
        rl.alerts_checked = alerts_checked
        rl.emails_sent = emails_sent
        rl.api_calls = api_calls
        db.add(rl)
        db.commit()
        db.close()
        log.info("Run completato: utenti=%s alert=%s email=%s chiamate=%s",
                 users_checked, alerts_checked, emails_sent, api_calls)


if __name__ == "__main__":
    # assicura che le tabelle esistano anche se il worker gira per primo
    from .db import Base
    from .migrations import run_migrations
    Base.metadata.create_all(engine)
    run_migrations(engine)
    run_worker()
