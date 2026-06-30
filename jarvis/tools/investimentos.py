"""tools/investimentos.py — Sugestões de carteira por perfil (tabelas estáticas).

Conteúdo 100% local. Mantido como @tool pra LangGraph rotear pelo nome.
"""

from __future__ import annotations

from langchain_core.tools import tool

_TABELAS: dict[str, str] = {
    "conservador": """
💰 PERFIL CONSERVADOR — Foco em segurança e liquidez

| Ativo       | %    | Por quê                       |
|-------------|------|-------------------------------|
| Tesouro Selic| 40%  | Segurança máxima             |
| CDB 100%+ CDI| 30% | Liquidez diária              |
| LCI / LCA    | 20%  | Isenção IR                   |
| Fundo DI     | 10%  | Diversificação               |

📌 CDI atual: ~10,65% a.a. SELIC: 10,75% a.a.
""",
    "moderado": """
⚖️ PERFIL MODERADO — Equilíbrio entre risco e retorno

| Ativo                 | %   | Característica     |
|-----------------------|-----|--------------------|
| Tesouro IPCA+         | 25% | Proteção inflação  |
| CDB / LCI / LCA       | 25% | Renda fixa         |
| FIIs (fundos imob.)   | 20% | Renda mensal       |
| Ações blue chips      | 20% | Longo prazo        |
| ETFs (BOVA11)         | 10% | Diversificação     |

📌 Destaques: KNRI11, HGLG11, PETR4, VALE3, WEGE3
""",
    "arrojado": """
🚀 PERFIL ARROJADO — Maior risco, maior potencial

| Ativo                  | %   | Característica       |
|------------------------|-----|----------------------|
| Ações growth           | 40% | Alto potencial       |
| ETFs internacionais    | 20% | Diversif. global     |
| FIIs                   | 15% | Renda passiva        |
| Cripto (BTC/ETH)       | 10% | Alta volatilidade    |
| Renda fixa             | 15% | Reserva emergência   |

📌 Atenção: mantenha sempre 6 meses de despesas em RF
""",
}


@tool
def analisar_investimentos(perfil: str = "moderado") -> str:
    """Retorna análise e sugestões de investimentos para o perfil
    informado (conservador | moderado | arrojado)."""
    pk = perfil.lower().strip()
    for k in _TABELAS:
        if k in pk:
            return _TABELAS[k]
    return _TABELAS["moderado"]
