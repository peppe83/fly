"""Istanza condivisa dei template Jinja2."""
import time

from fastapi.templating import Jinja2Templates

from .config import settings

templates = Jinja2Templates(directory="templates")
templates.env.globals["APP_NAME"] = settings.APP_NAME
# Versione degli asset statici: cambia a ogni avvio del server, così il browser
# non resta su una copia vecchia di app.js / style.css (cache-busting).
templates.env.globals["ASSET_VER"] = int(time.time())
