"""Configurazione applicativa letta da .env (vedi .env.example)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App / server
    APP_NAME: str = "flynotify"
    APP_ENV: str = "development"
    APP_BASE_URL: str = "http://localhost:8000"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEFAULT_TIMEZONE: str = "Europe/Rome"
    DEFAULT_CURRENCY: str = "EUR"

    # Database: se DATABASE_URL è vuoto, si costruisce da DB_* (MySQL),
    # e se mancano le credenziali si ripiega su SQLite (sviluppo zero-config).
    DATABASE_URL: str = ""
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_NAME: str = "flynotify"
    DB_USER: str = "flynotify"
    DB_PASSWORD: str = ""

    # JWT / auth
    JWT_SECRET: str = "dev-secret-change-me-please-use-a-long-random-value-32b+"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 720

    # Amadeus
    AMADEUS_CLIENT_ID: str = ""
    AMADEUS_CLIENT_SECRET: str = ""
    AMADEUS_BASE_URL: str = "https://test.api.amadeus.com"
    AMADEUS_TIMEOUT_SECONDS: int = 15

    # Travelpayouts
    TRAVELPAYOUTS_TOKEN: str = ""
    TRAVELPAYOUTS_MARKER: str = ""
    TRAVELPAYOUTS_BASE_URL: str = "https://api.travelpayouts.com"
    TRAVELPAYOUTS_CURRENCY: str = "eur"

    # SerpApi — Google Flights (fonte LIVE per la ricerca on-demand della dashboard).
    # Gli alert restano su Travelpayouts per non consumare la quota a pagamento.
    SERPAPI_KEY: str = ""
    SERPAPI_BASE_URL: str = "https://serpapi.com"
    SERPAPI_TIMEOUT_SECONDS: int = 30
    # "Ovunque" ibrido: Travelpayouts scopre le mete, SerpApi riprezza le prime N
    # con prezzi reali. 0 = disattiva la riprezzatura live (solo prezzi indicativi).
    EXPLORE_LIVE_TOP_N: int = 5
    # Numero massimo di mete restituite da "Ovunque" (catalogo Travelpayouts).
    EXPLORE_MAX_DESTINATIONS: int = 100

    # Kiwi.com (Tequila API) — seconda fonte LIVE con ottima copertura low-cost.
    # Supporta ricerca per RANGE di date e "ovunque" in una sola chiamata.
    # Gli alert NON la usano (resta tra le fonti live, mai nel catalogo).
    KIWI_API_KEY: str = ""
    KIWI_BASE_URL: str = "https://api.tequila.kiwi.com"
    KIWI_TIMEOUT_SECONDS: int = 20
    KIWI_SEARCH_LIMIT: int = 60

    # Ricerca su catalogo (Travelpayouts) per la DASHBOARD: più larga = più risultati.
    CATALOG_SEARCH_LIMIT: int = 200   # righe per chiamata (max API: 1000)
    CATALOG_SEARCH_MONTHS: int = 2    # mesi scansionati a partire dalla data scelta

    # Email (Gmail)
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""
    EMAIL_FROM_NAME: str = "flynotify"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    EMAIL_DAILY_CAP: int = 450

    # Scheduler / worker
    MIN_POLL_INTERVAL_HOURS: int = 2
    DEFAULT_POLL_INTERVAL_HOURS: int = 6
    WORKER_LOCK_NAME: str = "flynotify_worker"
    CALL_BUDGET_SOFT_LIMIT: int = 2000
    FIRST_CHECK_ON_CREATE: bool = True
    # Tetto di date-candidate interrogate per alert in un run. ANY (ovunque) è più
    # basso perché ogni data è già una chiamata multi-destinazione. Dimensionati per
    # coprire ~6 mesi di weekend: Sab+Dom ~52, Ven o Sab ~26.
    ALERT_MAX_CANDIDATES: int = 62
    ALERT_MAX_ANY_CANDIDATES: int = 56

    # Tetti di piano
    MAX_USERS: int = 50
    MAX_ALERTS_PER_USER: int = 5
    MAX_DATE_OFFSET_DAYS: int = 14   # finestra ± giorni attorno alla data scelta (dashboard)

    # Feature flag
    ENABLE_ALERTS: bool = True
    ENABLE_GUIDE: bool = False
    ENABLE_LLM: bool = False

    # Scheda destinazione
    OPENTRIPMAP_API_KEY: str = ""
    TICKETMASTER_API_KEY: str = ""
    OPENMETEO_BASE_URL: str = "https://api.open-meteo.com"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    @property
    def sqlalchemy_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        if self.DB_PASSWORD:
            return (
                f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
            )
        # Fallback sviluppo: SQLite locale (nessuna configurazione richiesta)
        return "sqlite:///./flynotify.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
