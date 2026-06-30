"""errors.py — Exceções tipadas do jarvis.

Substituem o uso de `Exception` genérico, permitindo:
  - Captura cirúrgica (não engole tudo)
  - Mensagens amigáveis ao usuário SEM vazar stack/details internos
  - Logs estruturados por tipo

Hierarquia:
  JarvisError (raiz)
    ├── ConfigError        → setup incompleto (avisa + instrui)
    ├── ToolError          → falha em uma tool (rede, parsing)
    ├── AuthError          → OAuth ou credenciais inválidas
    ├── UpstreamError      → API externa fora (Yahoo, OpenWeather, etc.)
    └── RateLimitError     → limite do usuário/API
"""

from __future__ import annotations


class JarvisError(Exception):
    """Raiz. Mensagem aqui é SEMPRE segura pra mostrar pro usuário."""

    http_status: int = 500

    def __init__(self, mensagem: str, *, detalhe: str | None = None) -> None:
        super().__init__(mensagem)
        self.user_message = mensagem
        self.internal_detail = detalhe
        # detalhe fica só em log, nunca é serializado pra resposta HTTP


class ConfigError(JarvisError):
    http_status = 500


class ToolError(JarvisError):
    http_status = 502


class AuthError(JarvisError):
    http_status = 401


class UpstreamError(JarvisError):
    """Falha em API externa (timeout, 5xx, JSON malformado)."""
    http_status = 502


class RateLimitError(JarvisError):
    http_status = 429


def safe_error_payload(exc: JarvisError) -> dict:
    """Serializa erro pra resposta HTTP — sem vazar detalhe interno."""
    return {"erro": exc.user_message, "tipo": exc.__class__.__name__}
