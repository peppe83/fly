"""Preferenze utente: ciascuno sceglie il PROPRIO intervallo (>= minimo globale)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import PasswordChange, PreferencesUpdate
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/me", tags=["preferences"])


@router.get("/preferences")
def get_prefs(user: User = Depends(get_current_user)):
    return {
        "poll_interval_hours": user.poll_interval_hours,
        "currency": user.currency,
        "timezone": user.timezone,
        "min_poll_interval_hours": settings.MIN_POLL_INTERVAL_HOURS,
    }


@router.put("/preferences")
def update_prefs(body: PreferencesUpdate, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if body.poll_interval_hours < settings.MIN_POLL_INTERVAL_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"L'intervallo minimo è {settings.MIN_POLL_INTERVAL_HOURS} ore")
    user.poll_interval_hours = body.poll_interval_hours
    user.currency = (body.currency or "EUR").upper()[:3]
    user.timezone = body.timezone or user.timezone
    db.commit()
    return {"poll_interval_hours": user.poll_interval_hours,
            "currency": user.currency, "timezone": user.timezone}


@router.put("/password")
def change_password(body: PasswordChange, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password attuale non corretta")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400,
                            detail="La nuova password deve essere diversa da quella attuale")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
