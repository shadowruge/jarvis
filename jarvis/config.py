"""config.py — Configuração centralizada do jarvis.

Lê variáveis de ambiente uma vez, valida formato crítico, expõe
constantes tipadas. Substitui o uso direto de `os.environ.get()`
espalhado pelo código.

Princípios:
  - Valores derivados de env têm default seguro (produção)
  - Constantes de domínio (MAX_MESSAGE_LEN, PORTAL_TIMEOUT) ficam aqui
  - Nada de segredos em default — sempre via .env
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env uma única vez no boot do processo
load_dotenv()

log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
OUTPUT_DIR   = DATA_DIR / "outputs"
LOG_DIR      = DATA_DIR / "logs"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"

for d in (DATA_DIR, OUTPUT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Segurança ────────────────────────────────────────────────────
MAX_CONTENT_LENGTH = 64 * 1024       # 64 KB — JSON do /chat (mitiga payload DoS)
MAX_MESSAGE_LEN    = 2000            # limite adicional no campo "mensagem"
SESSION_COOKIE_SECURE = os.environ.get("FLASK_COOKIE_SECURE", "0") == "1"

# ── Ollama / LLM ─────────────────────────────────────────────────
OLLAMA_HOST   = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL  = os.environ.get("OLLAMA_MODEL", "minimax-m3:cloud")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))

# ── APIs externas ────────────────────────────────────────────────
OPENWEATHER_API_KEY  = os.environ.get("OPENWEATHER_API_KEY", "").strip()
FOOTBALL_API_KEY     = os.environ.get("FOOTBALL_API_KEY", "").strip()
MAPBOX_API_KEY       = os.environ.get("MAPBOX_API_KEY", "").strip()
FAVORITE_DESTINATIONS = os.environ.get("FAVORITE_DESTINATIONS", "").strip()

# ── Scheduler / coleta de notícias ───────────────────────────────
NEWS_SCHEDULE = {
    "morning":   os.environ.get("NEWS_SCHEDULE_MORNING",   "08:00"),
    "noon":      os.environ.get("NEWS_SCHEDULE_NOON",      "12:00"),
    "afternoon": os.environ.get("NEWS_SCHEDULE_AFTERNOON", "18:00"),
    "night":     os.environ.get("NEWS_SCHEDULE_NIGHT",     "21:00"),
}

# ── HTTP ─────────────────────────────────────────────────────────
HTTP_TIMEOUT_DEFAULT = 10
HTTP_TIMEOUT_RETRY   = 3      # tentativas
HTTP_MAX_CONCURRENCY = 6

# ── Flask ────────────────────────────────────────────────────────
def load_flask_secret_key() -> str:
    """Carrega FLASK_SECRET_KEY de env ou arquivo persistente.

    Fallback seguro: gera uma chave e persiste em `data/.flask_secret`
    para sobreviver a reinícios do processo (Flask invalida sessões
    quando a chave muda).
    """
    key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if key:
        return key

    persist_file = DATA_DIR / ".flask_secret"
    if persist_file.exists():
        stored = persist_file.read_text().strip()
        if stored:
            log.warning(
                "⚠️ FLASK_SECRET_KEY não definida no .env — usando chave "
                "persistida em %s. Defina uma no .env para produção!",
                persist_file,
            )
            return stored

    # Primeira execução: gera e persiste
    new_key = secrets.token_hex(32)
    persist_file.write_text(new_key)
    persist_file.chmod(0o600)
    log.info("🔑 Gerada nova FLASK_SECRET_KEY persistida em %s", persist_file)
    return new_key


# ── Constantes de domínio ────────────────────────────────────────
DEFAULT_HOME = "Rua Voluntários da Pátria, 100, Botafogo, Rio de Janeiro"

RJ_BAIRROS: dict[str, str] = {
    "copacabana": "Copacabana, Rio de Janeiro, RJ, Brasil",
    "ipanema":    "Ipanema, Rio de Janeiro, RJ, Brasil",
    "leblon":     "Leblon, Rio de Janeiro, RJ, Brasil",
    "botafogo":   "Botafogo, Rio de Janeiro, RJ, Brasil",
    "flamengo":   "Flamengo, Rio de Janeiro, RJ, Brasil",
    "lapa":       "Lapa, Rio de Janeiro, RJ, Brasil",
    "centro":     "Centro, Rio de Janeiro, RJ, Brasil",
    "tijuca":     "Tijuca, Rio de Janeiro, RJ, Brasil",
    "barra":      "Barra da Tijuca, Rio de Janeiro, RJ, Brasil",
    "urca":       "Urca, Rio de Janeiro, RJ, Brasil",
    "catete":     "Catete, Rio de Janeiro, RJ, Brasil",
    "laranjeiras":"Laranjeiras, Rio de Janeiro, RJ, Brasil",
    "glória":     "Glória, Rio de Janeiro, RJ, Brasil",
    "méier":      "Méier, Rio de Janeiro, RJ, Brasil",
    "maracanã":   "Maracanã, Rio de Janeiro, RJ, Brasil",
    "recreio":    "Recreio dos Bandeirantes, Rio de Janeiro, RJ, Brasil",
    "niterói":    "Niterói, RJ, Brasil",
}


@dataclass(frozen=True)
class AgentConfig:
    """Configuração congelada do agente (imutável após build)."""
    model: str = OLLAMA_MODEL
    base_url: str = OLLAMA_HOST
    temperature: float = 0.3
    num_predict: int = 1024
    num_ctx: int = 4096
    repeat_penalty: float = 1.2
    think_mode: bool = False


def agent_config() -> AgentConfig:
    """Builder que resolve env em tempo de boot."""
    return AgentConfig(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_HOST,
        temperature=float(os.environ.get("AGENT_TEMPERATURE", "0.3")),
        num_predict=int(os.environ.get("AGENT_NUM_PREDICT", "1024")),
        num_ctx=int(os.environ.get("AGENT_NUM_CTX", "4096")),
    )
