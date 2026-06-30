"""
main.py — Bootstrap do jarvis (Flask + agente).

Estrutura:
  jarvis/
    config.py        → env vars, constantes, paths, AgentConfig dataclass
    errors.py        → exceções tipadas (sem vazamento de str(e))
    http_client.py   → httpx singleton com retry
    agent.py         → LangGraph + Ollama + singleton
    system_prompt.txt → prompt carregado de arquivo (separado do código)
    tools/           → 8 tools agrupadas por domínio
    routes/          → 4 blueprints (home, dashboard, google_extras, chat)

Variáveis de ambiente: veja README.md / .env.example

Para rodar:
    python main.py              # desenvolvimento
    gunicorn -w 4 main:app      # produção (Linux)
    waitress-serve main:app     # produção (Windows)
"""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

from flask import Flask

from jarvis.config import (
    LOG_DIR,
    MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE,
    load_flask_secret_key,
)
from jarvis.http_client import shutdown as http_shutdown
from jarvis.routes import register_routes

# ── Logging ──────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "jarvis.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("jarvis")

# ── Flask app ────────────────────────────────────────────────────
_PACKAGE_DIR = Path(__file__).parent / "jarvis"
app = Flask(
    __name__,
    template_folder=str(_PACKAGE_DIR / "templates"),
)
app.secret_key = load_flask_secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    JSON_AS_ASCII=False,
)

# ── Rotas (Blueprints) ───────────────────────────────────────────
register_routes(app)


# ── Shutdown handlers (fecha tudo limpo) ────────────────────────
def _cleanup() -> None:
    """Fecha recursos na ordem inversa da abertura."""
    logger.info("🛑 Encerrando jarvis…")
    http_shutdown()


atexit.register(_cleanup)


# ── Bootstrap ────────────────────────────────────────────────────
if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    logger.info(
        "🚀 jarvis iniciando — modelo: %s, host: 0.0.0.0:%d (debug=%s)",
        os.environ.get("OLLAMA_MODEL", "minimax-m3:cloud"),
        port,
        debug,
    )
    logger.info("📝 Logs em %s", LOG_DIR / "jarvis.log")

    # use_reloader=False evita spawn duplicado em dev (e bug do singleton agente)
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
