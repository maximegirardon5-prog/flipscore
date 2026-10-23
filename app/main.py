"""Point d'entrée de l'application web (FastAPI).

Lancement local :  ./run.sh dev   puis ouvrir http://localhost:8000
Documentation de l'API générée automatiquement : http://localhost:8000/docs
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app import __version__
from app.core.business_config import get_business_config
from app.core.errors import ConfigError
from app.core.logging import get_logger, setup_logging
from app.core.settings import get_settings
from app.db.session import session_scope
from app.sources.registry import discover_connectors

log = get_logger(__name__)
templates = Jinja2Templates(directory=Path(__file__).parent / "web" / "templates")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.is_production)
    log.info("démarrage", extra={"env": settings.app_env, "version": __version__})
    yield


app = FastAPI(title="FlipScore", version=__version__, lifespan=lifespan)


def _status() -> dict:
    """État de santé : configuration lisible ? base joignable ?"""
    status: dict = {"version": __version__, "env": get_settings().app_env}
    try:
        cfg = get_business_config()
        status["config"] = {
            "ok": True,
            "categories": sorted(cfg.categories),
            "platforms": sorted(cfg.platforms),
        }
    except ConfigError as e:
        status["config"] = {"ok": False, "error": str(e)}
    try:
        with session_scope() as db:
            db.execute(text("SELECT 1"))
        status["database"] = {"ok": True}
    except Exception as e:  # base injoignable : on le signale sans planter la page
        log.warning("base injoignable", extra={"error": str(e)})
        status["database"] = {"ok": False, "error": type(e).__name__}
    status["connectors"] = sorted(discover_connectors())
    status["ok"] = status["config"]["ok"] and status["database"]["ok"]
    return status


@app.get("/health")
def health() -> JSONResponse:
    status = _status()
    return JSONResponse(status, status_code=200 if status["ok"] else 503)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"status": _status()})
