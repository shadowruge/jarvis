"""routes/__init__.py — Monta os blueprints e registra no Flask app.

Cada domínio em arquivo separado:
  - home.py        → / e /api/info
  - dashboard.py   → cards (/api/bolsa, /api/noticias, etc.)
  - google_extras.py → /api/agenda, /api/emails
  - chat.py        → /chat (sync) e /chat/stream (SSE)
"""

from __future__ import annotations

from flask import Flask

from .chat import bp as chat_bp
from .dashboard import bp as dashboard_bp
from .google_extras import bp as google_bp
from .home import bp as home_bp


def register_routes(app: Flask) -> None:
    """Registra todos os blueprints da app."""
    app.register_blueprint(home_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(google_bp)
    app.register_blueprint(chat_bp)
