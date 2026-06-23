"""
main.py — Bootstrap do jarvis (Flask + agente).

Estrutura (refatorado):
  - tools.py   → todas as @tool (notícias, bolsa, clima, google, etc.)
  - agent.py   → construção do LangGraph + LLM + memória
  - routes.py  → rotas Flask (cards do dashboard + chat)
  - main.py    → este arquivo: só inicializa o Flask e sobe o servidor

Para rodar:
    python main.py

Variáveis de ambiente (opcionais): veja README.md
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask
from dotenv import load_dotenv

# Carrega .env ANTES de qualquer outra coisa
load_dotenv()

# ── Logging ──────────────────────────────────────────────────────
LOG_DIR = Path("data/logs")
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
logger = logging.getLogger(__name__)

# ── Flask app ────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())
app.config["JSON_AS_ASCII"] = False

# ── Rotas ────────────────────────────────────────────────────────
# Import lazy pra não criar ciclo (routes.py importa de agent.py que importa de tools.py)
from routes import register_routes
register_routes(app)


# ── Bootstrap ────────────────────────────────────────────────────
if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info(
        f"🚀 jarvis iniciando — modelo: {os.environ.get('OLLAMA_MODEL', 'minimax-m3:cloud')}"
    )
    logger.info(f"📝 Logs em {LOG_DIR}/jarvis.log")
    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=False)