"""tools/clima.py — OpenWeather (atual + previsão).

Replace do `clima_rio_janeiro()` original. Permanece um único tool
mas com type hints e falhas amigáveis.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from langchain_core.tools import tool

from ..config import OPENWEATHER_API_KEY
from ..http_client import get_json

log = logging.getLogger(__name__)

# Rio de Janeiro (Centro)
RJ_LAT, RJ_LON = -22.9068, -43.1729

_PREVISOES_VALIDAS = ("atual", "hoje", "amanha", "3dias", "5dias")


def _sem_chave() -> str:
    return (
        "⚠️ OPENWEATHER_API_KEY não configurada.\n"
        "Cadastre-se grátis em https://openweathermap.org/api e adicione no .env"
    )


@tool
def clima_atual_e_previsao(previsao: str = "atual") -> str:
    """Busca clima atual ou previsão do Rio de Janeiro via OpenWeather.

    Args:
        previsao: 'atual' (default) | 'hoje' | 'amanha' | '3dias' | '5dias'.
    """
    if not OPENWEATHER_API_KEY:
        return _sem_chave()

    p = previsao.lower().strip()
    if p not in _PREVISOES_VALIDAS:
        return f"⚠️ pre-visão '{previsao}' inválida. Use uma de: {', '.join(_PREVISOES_VALIDAS)}"

    try:
        if p == "atual":
            data = get_json(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": RJ_LAT, "lon": RJ_LON,
                    "appid": OPENWEATHER_API_KEY,
                    "lang": "pt_br", "units": "metric",
                },
            )
            main = data["main"]
            return (
                f"🌤️ **Clima agora em {data.get('name', 'Rio de Janeiro')}**\n\n"
                f"📍 {data['weather'][0]['description'].capitalize()}\n"
                f"🌡️ Temperatura: {main['temp']:.1f}°C (sensação {main['feels_like']:.1f}°C)\n"
                f"💧 Umidade: {main['humidity']}%\n"
                f"💨 Vento: {data['wind']['speed']} m/s\n"
                f"🖼️ Ícone: {data['weather'][0]['icon']}"
            )

        # Forecast 5 dias / 3h
        data = get_json(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "lat": RJ_LAT, "lon": RJ_LON,
                "appid": OPENWEATHER_API_KEY,
                "lang": "pt_br", "units": "metric",
            },
        )
        por_dia: dict[str, list[dict]] = defaultdict(list)
        for e in data["list"]:
            por_dia[e["dt_txt"][:10]].append(e)

        dias = sorted(por_dia.keys())
        if p == "hoje" or p == "atual":
            itens, alvo = por_dia[dias[0]][:8], dias[0]
        elif p == "amanha" and len(dias) > 1:
            itens, alvo = por_dia[dias[1]][:8], dias[1]
        elif p == "3dias":
            itens = sum((por_dia[d][:3] for d in dias[:3]), [])
            alvo = "próximos 3 dias"
        else:  # 5dias
            itens = sum((por_dia[d][:2] for d in dias[:5]), [])
            alvo = "próximos 5 dias"

        tmin = min(e["main"]["temp_min"] for e in itens)
        tmax = max(e["main"]["temp_max"] for e in itens)
        chuva = sum(e.get("rain", {}).get("3h", 0) for e in itens)
        descs = ", ".join(sorted({e["weather"][0]["description"] for e in itens}))

        return (
            f"🌦️ **Previsão — {alvo} (Rio de Janeiro)**\n\n"
            f"🌡️ Mín: {tmin:.1f}°C / Máx: {tmax:.1f}°C\n"
            f"🌧️ Chuva prevista: {chuva:.1f} mm\n"
            f"📋 Condições: {descs.capitalize()}"
        )

    except Exception as e:
        log.warning("OpenWeather falhou: %s", e)
        return f"⚠️ Erro ao buscar clima: {e}"
