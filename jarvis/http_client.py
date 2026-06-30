"""http_client.py — Cliente HTTP compartilhado com retry e logging.

Substitui as dezenas de `httpx.get(...)` soltos pelo código.
Benefícios:
  - Connection pooling (latência cai em rajada)
  - Retry exponencial em 5xx / timeout
  - User-Agent e headers consistentes
  - Logging centralizado de cada chamada

Uso típico:
    from http_client import get_json
    data = get_json("https://api.exemplo.com/v1/x")
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "jarvis-agente/1.0 (+https://github.com/shadowruge/jarvis)",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    """Singleton lazy — module-level é thread-safe só na 1ª chamada."""
    global _client
    if _client is None:
        _client = httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            http2=False,
        )
    return _client


def _retry(callable_, *, tentativas: int = 3, base_delay: float = 0.5) -> Any:
    """Retry exponencial simples. 5xx e timeouts disparam retry."""
    last: Exception | None = None
    for i in range(tentativas):
        try:
            return callable_()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last = e
            delay = base_delay * (2 ** i)
            log.warning("Tentativa %d/%d falhou: %s. Retry em %.1fs",
                        i + 1, tentativas, e, delay)
        except httpx.HTTPStatusError as e:
            # 5xx → retry; 4xx → propaga
            if 500 <= e.response.status_code < 600:
                last = e
                delay = base_delay * (2 ** i)
                log.warning("5xx (%d) na tentativa %d. Retry em %.1fs",
                            e.response.status_code, i + 1, delay)
            else:
                raise
        import time
        time.sleep(delay)
    raise last or RuntimeError("retry esgotou sem erro claro")


def get_json(url: str, *, params: dict | None = None, timeout: float = 10.0) -> dict:
    """GET + parse JSON com retry."""
    def _do():
        r = _get_client().get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    return _retry(_do)


def get_text(url: str, *, params: dict | None = None, timeout: float = 10.0) -> str:
    """GET + texto."""
    def _do():
        r = _get_client().get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.text
    return _retry(_do)


def get_bytes(url: str, *, params: dict | None = None, timeout: float = 10.0) -> bytes:
    """GET + bytes (imagens, PDFs)."""
    def _do():
        r = _get_client().get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.content
    return _retry(_do)


def shutdown() -> None:
    """Fecha o cliente. Chame em atexit/shutdown limpo."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
