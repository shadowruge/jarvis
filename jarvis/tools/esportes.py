"""tools/esportes.py — Times cariocas + Brasileirão.

Suporta 2 provedores:
  - FOOTBALL_API_KEY definida → API-Football (dados completos, standings)
  - Sem chave                  → ESPN público (fallback)

Unifica os antigos `estatisticas_esportes` em um tool com nomes claros.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from ..config import FOOTBALL_API_KEY
from ..http_client import get_json

log = logging.getLogger(__name__)

# API-Football IDs
API_FOOTBALL_LEAGUES = {
    "brasileirao":  71,
    "libertadores": 13,
    "premier":      39,
    "copa_brasil":  72,
}
API_FOOTBALL_TEAMS = {
    "flamengo": 127, "flu": 128, "fluminense": 128, "fluflu": 128,
    "vasco": 130, "botafogo": 131,
}
API_FOOTBALL_TIMES_VALIDOS = set(API_FOOTBALL_LEAGUES) | set(API_FOOTBALL_TEAMS)


def _espn_jogos_do_dia() -> str:
    """Jogos do dia (todos os esportes) — ESPN scoreboard."""
    try:
        data = get_json("https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard")
        jogos = []
        for ev in data.get("events", [])[:10]:
            comp = ev.get("competitions", [{}])[0]
            teams = comp.get("competitors", [])
            if len(teams) >= 2:
                home = teams[0]["team"]["name"]
                away = teams[1]["team"]["name"]
                hs = teams[0].get("score", "?")
                aws = teams[1].get("score", "?")
                status = comp.get("status", {}).get("type", {}).get("description", "")
                jogos.append(f"⚽ {home} {hs} x {aws} {away}  _{status}_")
        return "\n".join(jogos) if jogos else "Sem jogos disponíveis no momento."
    except Exception as e:
        log.warning("ESPN scoreboard falhou: %s", e)
        return "⚠️ Sem dados de jogos disponíveis."


def _espn_brasileirao_standings() -> str:
    """Classificação do Brasileirão Série A via ESPN (público, sem chave).

    Endpoint: .../apis/v2/sports/soccer/bra.1/standings (o `/v1/` não retorna data)
    """
    try:
        data = get_json(
            "https://site.api.espn.com/apis/v2/sports/soccer/bra.1/standings"
        )
        # Estrutura: data.children[0].standings.entries[]
        grupos = (
            (data.get("children") or [{}])[0].get("standings", {}).get("entries", [])
            or data.get("standings", {}).get("entries", [])
        )
        if not grupos:
            return ""
        linhas = ["📊 **Classificação — Brasileirão Série A**\n"]
        for i, e in enumerate(grupos[:10], 1):
            team = e.get("team", {}).get("displayName", "?")
            stats = {s["name"]: s.get("value") for s in e.get("stats", []) if "name" in s}
            pts   = stats.get("points", "?")
            jogos = stats.get("gamesPlayed", stats.get("played", "?"))
            v = stats.get("wins",   stats.get("w", "?"))
            e_ = stats.get("ties",  stats.get("d", "?"))
            d = stats.get("losses", stats.get("l", "?"))
            linhas.append(
                f"{i:2d}. {team:25s}  {pts} pts  ({jogos}J {v}V {e_}E {d}D)"
            )
        return "\n".join(linhas)
    except Exception as e:
        log.warning("ESPN standings falhou: %s", e)
        return ""


def _via_api_football(esporte: str) -> str:
    headers = {"x-apisports-key": FOOTBALL_API_KEY}
    base = "https://v3.football.api-sports.io"

    if esporte in API_FOOTBALL_TEAMS:
        team_id = API_FOOTBALL_TEAMS[esporte]
        linhas = [f"⚽ **Próximos jogos — {esporte.capitalize()}**\n"]

        data = get_json(f"{base}/fixtures", params={"team": team_id, "next": 3})
        for j in data.get("response", [])[:3]:
            dt = j["fixture"]["date"]
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            liga = j["league"]["name"]
            linhas.append(f"📅 {dt[:10]} {dt[11:16]} | {home} x {away} _({liga})_")

        try:
            st = get_json(f"{base}/standings", params={"team": team_id, "season": 2026})
            if st.get("response"):
                team = st["response"][0]["league"]["standings"][0][0]
                linhas.append(
                    f"\n📊 Brasileirão 2026: {team['rank']}º lugar, "
                    f"{team['points']} pts em {team['all']['played']} jogos"
                )
        except Exception:
            pass

        return "\n".join(linhas)

    # League
    league_id = API_FOOTBALL_LEAGUES[esporte]
    data = get_json(f"{base}/standings", params={"league": league_id, "season": 2026})
    standings = data.get("response", [])
    if not standings:
        return f"📊 Sem classificação disponível para {esporte} em 2026."

    linhas = [f"📊 **Classificação — {esporte.capitalize()} 2026**\n"]
    table = standings[0]["league"]["standings"][0]
    for i, t in enumerate(table[:10], 1):
        linhas.append(
            f"{i:2d}. {t['team']['name']:25s}  {t['points']} pts  "
            f"({t['all']['played']}J {t['all']['win']}V {t['all']['draw']}E {t['all']['lose']}D)"
        )
    return "\n".join(linhas)


@tool
def esportes_cariocas(esporte: str = "brasileirao") -> str:
    """Estatísticas esportivas dos 4 grandes do Rio + principais ligas.

    Args:
        esporte: 'flamengo' | 'flu' | 'vasco' | 'botafogo' | 'brasileirao'
                | 'libertadores' | 'premier' | 'copa_brasil'.

    Requer FOOTBALL_API_KEY no .env para dados completos.
    Sem a chave, usa ESPN público.
    """
    esporte = esporte.lower().strip()

    if esporte not in API_FOOTBALL_TIMES_VALIDOS:
        return (
            f"⚠️ Esporte '{esporte}' não reconhecido. "
            f"Use um de: {', '.join(sorted(API_FOOTBALL_TIMES_VALIDOS))}"
        )

    if FOOTBALL_API_KEY:
        try:
            return _via_api_football(esporte)
        except Exception as e:
            log.warning("API-Football falhou, usando ESPN: %s", e)
            # continua pro fallback abaixo

    # Sem chave de API (ou falhou) → usa ESPN público.
    # Para ligas dá classificação via standings; para times cai pros jogos do dia.
    if esporte == "brasileirao":
        cls = _espn_brasileirao_standings()
        if cls:
            return (
                cls
                + "\n\n💡 Para dados completos (todos os times, posições exatas), "
                + "configure FOOTBALL_API_KEY no .env — grátis em api-football.com"
            )

    return (
        f"📋 **Jogos de hoje (ESPN público — {esporte})**\n\n"
        + _espn_jogos_do_dia()
        + "\n\n💡 Para classificação e dados completos de "
        + ("Brasileirão / " if esporte != "brasileirao" else "")
        + f"{esporte}, configure FOOTBALL_API_KEY no .env — grátis em api-football.com"
    )
