"""tools/bolsa.py — Cotações da B3 via Yahoo Finance.

Usa o cliente HTTP compartilhado (retry + pool).
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from ..http_client import get_json

log = logging.getLogger(__name__)

TICKERS_PRINCIPAIS = (
    "^BVSP", "PETR4.SA", "VALE3.SA", "ITUB4.SA",
    "BBDC4.SA", "MGLU3.SA", "WEGE3.SA",
)

_LABELS = {
    "^BVSP":   "IBOVESPA",
    "PETR4.SA":"PETR4",
    "VALE3.SA":"VALE3",
    "ITUB4.SA":"ITUB4",
    "BBDC4.SA":"BBDC4",
    "MGLU3.SA":"MGLU3",
    "WEGE3.SA":"WEGE3",
}


@tool
def dados_bolsa() -> str:
    """Retorna Ibovespa + principais ações da B3 em tempo real
    (PETR4, VALE3, ITUB4, BBDC4, MGLU3, WEGE3). Use para 'bolsa',
    'ibovespa', 'ações', 'cotação'."""
    linhas: list[str] = []
    for ticker in TICKERS_PRINCIPAIS:
        try:
            data = get_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                params={"range": "1d", "interval": "1d"},
            )
            meta = data["chart"]["result"][0]["meta"]
            preco    = float(meta.get("regularMarketPrice", 0))
            anterior = float(meta.get("previousClose", preco))
            variacao = ((preco - anterior) / anterior * 100) if anterior else 0.0
            sinal    = "🟢" if variacao >= 0 else "🔴"
            linhas.append(f"{sinal} {_LABELS[ticker]}: {preco:,.2f}  ({variacao:+.2f}%)")
        except Exception as e:
            log.warning("bolsa falhou para %s: %s", ticker, e)
            linhas.append(f"⚠️ {_LABELS[ticker]}: indisponível")

    return "\n".join(linhas)
