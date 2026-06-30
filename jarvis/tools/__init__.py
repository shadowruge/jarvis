"""tools/__init__.py — Registro central de tools do agente.

Decisão arquitetural:
  Para modelos pequenos (qwen3:0.6b) muitos tools degrada a qualidade
  de roteamento. Mantemos APENAS as 8 tools de altíssima utilidade
  no ALL_TOOLS. As demais ficam disponíveis via submódulos pra
  integração programática futura.

Tools expostas ao LLM (8):
  - buscar_panorama_rj       → notícias (agregada)
  - dados_bolsa              → Ibovespa + principais
  - clima_atual_e_previsao   → OpenWeather
  - esportes_cariocas       → Flamengo/Flu/Vasco/Botafogo + Brasileirão
  - analisar_investimentos   → carteira por perfil
  - classificar_email        → classificador rápido
  - calcular_rota_rio        → rotas RJ (favoritos + endereços)
  - gerenciar_agenda_gmail   → Calendar + Gmail (interface unificada)
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from .noticias import buscar_panorama_rj
from .bolsa import dados_bolsa
from .investimentos import analisar_investimentos
from .email import classificar_email
from .clima import clima_atual_e_previsao
from .esportes import esportes_cariocas
from .rotas import calcular_rota_rio
from .google import gerenciar_agenda_gmail


ALL_TOOLS: list[BaseTool] = [
    buscar_panorama_rj,
    dados_bolsa,
    clima_atual_e_previsao,
    esportes_cariocas,
    analisar_investimentos,
    classificar_email,
    calcular_rota_rio,
    gerenciar_agenda_gmail,
]


__all__ = ["ALL_TOOLS"]
