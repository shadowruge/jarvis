"""
tools.py — Todas as ferramentas (@tool) que o agente LangGraph consome.

Cada tool é uma função Python decorada com @tool do LangChain. O `@tool`
extrai nome, descrição (docstring) e esquema dos argumentos via Pydantic,
e expõe a função como "ferramenta" pro LLM chamar.

Organização:
  - Notícias / Bolsa / E-mails / Investimentos: conteúdo e classificação
  - Clima / Esportes / Rotas: APIs externas com fallback
  - Google Calendar / Gmail: wrappers finos sobre google_services.py
  - Coleta automática: pipeline + scheduler (apscheduler)

Otimização aplicada:
  - Todas as tools são robustas a falha de rede (try/except retornando string amigável)
  - Não dependem de Flask — podem ser invocadas em qualquer contexto
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from langchain_core.tools import tool

import google_services as gs

log = logging.getLogger(__name__)

# ── Pontos de interesse padrão no Rio ────────────────────────────
DEFAULT_HOME = "Rua Voluntários da Pátria, 100, Botafogo, Rio de Janeiro"

# ── Scheduler global (inicia desligado) ──────────────────────────
_scheduler = None


# ════════════════════════════════════════════════════════════════
# NOTÍCIAS
# ════════════════════════════════════════════════════════════════

@tool
def buscar_noticias_rj_brasil(tema: str = "geral") -> str:
    """Busca notícias recentes do Rio de Janeiro e do Brasil em 17 portais (RSS + HTML)."""
    if "news_scraper" not in sys.modules:
        try:
            import news_scraper  # noqa: F401
        except Exception as e:
            return f"⚠️ news_scraper não disponível: {e}"

    import news_scraper as ns

    async def _coletar():
        sem = asyncio.Semaphore(6)
        tarefas = [ns._raspar_portal(p, sem) for p in ns.PORTAIS]
        resultados = await asyncio.gather(*tarefas, return_exceptions=True)

        manchetes = []
        for r in resultados:
            if isinstance(r, Exception) or not r.get("manchetes"):
                continue
            for m in r["manchetes"]:
                manchetes.append(f"[{r['portal']}] {m}")
        return manchetes

    try:
        manchetes = asyncio.run(_coletar())
        if not manchetes:
            return "Sem notícias disponíveis no momento. Tente novamente em alguns minutos."
        return "\n".join(f"• {m}" for m in manchetes[:25])
    except Exception as e:
        # Fallback RSS simples
        try:
            r = httpx.get("https://g1.globo.com/rss/g1/rio-de-janeiro/", timeout=8, follow_redirects=True)
            titulos = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)[:8]
            if not titulos:
                titulos = re.findall(r"<title>(.*?)</title>", r.text)[1:9]
            if titulos:
                return "\n".join(f"• [G1 Rio] {t.strip()}" for t in titulos)
        except Exception:
            pass
        return f"⚠️ Erro ao buscar notícias: {e}"


# ════════════════════════════════════════════════════════════════
# BOLSA
# ════════════════════════════════════════════════════════════════

@tool
def buscar_bolsa_valores() -> str:
    """Busca dados em tempo real do Ibovespa e principais ações da B3."""
    try:
        tickers = ["^BVSP", "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "MGLU3.SA", "WEGE3.SA"]
        resultados = []
        for ticker in tickers:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
            r = httpx.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            data = r.json()
            meta = data["chart"]["result"][0]["meta"]
            preco    = meta.get("regularMarketPrice", 0)
            anterior = meta.get("previousClose", preco)
            variacao = ((preco - anterior) / anterior * 100) if anterior else 0
            sinal    = "🟢" if variacao >= 0 else "🔴"
            nome     = ticker.replace(".SA", "").replace("^BVSP", "IBOVESPA")
            resultados.append(f"{sinal} {nome}: {preco:,.2f}  ({variacao:+.2f}%)")
        return "\n".join(resultados)
    except Exception as e:
        return f"⚠️ Erro ao buscar bolsa: {e}"


# ════════════════════════════════════════════════════════════════
# E-MAIL (classificador local)
# ════════════════════════════════════════════════════════════════

@tool
def classificar_email(conteudo_email: str) -> str:
    """Classifica um e-mail e sugere ação. Recebe o texto completo do e-mail."""
    conteudo_lower = conteudo_email.lower()
    categorias = []
    if any(w in conteudo_lower for w in ["urgente", "prazo", "vencimento", "imediato", "deadline", "asap"]):
        categorias.append("🚨 URGENTE")
    if any(w in conteudo_lower for w in ["fatura", "boleto", "pix", "pagamento", "cobrança", "débito", "nota fiscal"]):
        categorias.append("💳 FINANCEIRO")
    if any(w in conteudo_lower for w in ["oferta", "promoção", "desconto", "grátis", "clique aqui", "ganhe", "compre"]):
        categorias.append("🗑️ SPAM/MARKETING")
    if any(w in conteudo_lower for w in ["reunião", "meeting", "proposta", "projeto", "contrato", "cliente"]):
        categorias.append("💼 TRABALHO")
    if any(w in conteudo_lower for w in ["família", "amigo", "feliz", "aniversário", "pessoal"]):
        categorias.append("👤 PESSOAL")
    if not categorias:
        categorias.append("📋 GERAL/INFORMATIVO")
    return f"Categorias detectadas: {', '.join(categorias)}"


# ════════════════════════════════════════════════════════════════
# INVESTIMENTOS
# ════════════════════════════════════════════════════════════════

_TABELAS_INVEST = {
    "conservador": """
💰 PERFIL CONSERVADOR — Foco em segurança e liquidez

 Tesouro Selic     40%  Segurança máxima
 CDB 100%+ CDI     30%  Liquidez diária
 LCI / LCA         20%  Isenção IR
 Fundo DI          10%  Diversificação

📌 CDI atual: ~10,65% a.a. SELIC: 10,75% a.a.
""",
    "moderado": """
⚖️ PERFIL MODERADO — Equilíbrio entre risco e retorno
┌─────────────────────────────────────────────────┐
│ Tesouro IPCA+       | 25% | Proteção inflação   │
│ CDB / LCI / LCA     | 25% | Renda fixa          │
│ FIIs (fundos imob.) | 20% | Renda mensal        │
│ Ações blue chips    | 20% | Longo prazo         │
│ ETFs (BOVA11)       | 10% | Diversificação      │
└─────────────────────────────────────────────────┘
📌 Destaques: KNRI11, HGLG11, PETR4, VALE3, WEGE3
""",
    "arrojado": """
🚀 PERFIL ARROJADO — Maior risco, maior potencial
┌─────────────────────────────────────────────────┐
│ Ações growth        | 40% | Alto potencial      │
│ ETFs internacionais | 20% | Diversif. global    │
│ FIIs                | 15% | Renda passiva       │
│ Cripto (BTC/ETH)    | 10% | Alta volatilidade   │
│ Renda fixa          | 15% | Reserva emergência  │
└─────────────────────────────────────────────────┘
📌 Atenção: mantenha sempre 6 meses de despesas em RF
""",
}


@tool
def analisar_investimentos(perfil: str = "moderado") -> str:
    """Retorna análise e sugestões de investimentos para o perfil dado (conservador/moderado/arrojado)."""
    pk = perfil.lower()
    for k in _TABELAS_INVEST:
        if k in pk:
            return _TABELAS_INVEST[k]
    return _TABELAS_INVEST["moderado"]


# ════════════════════════════════════════════════════════════════
# CLIMA
# ════════════════════════════════════════════════════════════════

@tool
def clima_rio_janeiro(previsao: str = "atual") -> str:
    """
    Busca informações do clima no Rio de Janeiro via OpenWeather.
    previsao: atual | hoje | amanha | 3dias | 5dias
    Requer OPENWEATHER_API_KEY no .env.
    """
    api_key = os.environ.get("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        return (
            "⚠️ OPENWEATHER_API_KEY não configurada.\n"
            "Cadastre-se grátis em https://openweathermap.org/api e adicione no .env"
        )

    lat, lon = -22.9068, -43.1729

    try:
        if previsao.lower() in ("atual", "agora"):
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&lang=pt_br&units=metric"
            r = httpx.get(url, timeout=10)
            r.raise_for_status()
            d = r.json()
            temp = d["main"]["temp"]
            sens = d["main"]["feels_like"]
            umid = d["main"]["humidity"]
            vento = d["wind"]["speed"]
            desc = d["weather"][0]["description"].capitalize()
            icone = d["weather"][0]["icon"]
            cidade = d.get("name", "Rio de Janeiro")
            return (
                f"🌤️ **Clima agora em {cidade}**\n\n"
                f"📍 {desc}\n"
                f"🌡️ Temperatura: {temp:.1f}°C (sensação {sens:.1f}°C)\n"
                f"💧 Umidade: {umid}%\n"
                f"💨 Vento: {vento} m/s\n"
                f"🖼️ Ícone OpenWeather: {icone}"
            )

        url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&lang=pt_br&units=metric"
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
        dados = r.json()["list"]

        dias = defaultdict(list)
        for e in dados:
            dias[e["dt_txt"][:10]].append(e)
        dias_ord = sorted(dias.keys())

        if previsao.lower() == "hoje":
            alvo, itens = dias_ord[0], dias[dias_ord[0]][:8]
        elif previsao.lower() == "amanha" and len(dias_ord) > 1:
            alvo, itens = dias_ord[1], dias[dias_ord[1]][:8]
        elif previsao.lower() in ("3dias", "tres"):
            dias_sel = dias_ord[:3]
            itens = sum((dias[d][:3] for d in dias_sel), [])
            alvo = "próximos 3 dias"
        elif previsao.lower() == "5dias":
            dias_sel = dias_ord[:5]
            itens = sum((dias[d][:2] for d in dias_sel), [])
            alvo = "próximos 5 dias"
        else:
            alvo, itens = dias_ord[0], dias[dias_ord[0]][:8]

        if not isinstance(itens, list):
            itens = [itens]

        temps_min = min(e["main"]["temp_min"] for e in itens)
        temps_max = max(e["main"]["temp_max"] for e in itens)
        chuva_total = sum(e.get("rain", {}).get("3h", 0) for e in itens)
        descs = ", ".join({e["weather"][0]["description"] for e in itens})
        return (
            f"🌦️ **Previsão — {alvo} (Rio de Janeiro)**\n\n"
            f"🌡️ Mín: {temps_min:.1f}°C / Máx: {temps_max:.1f}°C\n"
            f"🌧️ Chuva prevista: {chuva_total:.1f} mm\n"
            f"📋 Condições: {descs.capitalize()}"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "⚠️ Chave do OpenWeather inválida ou não ativada ainda (pode levar ~2h após cadastro)"
        return f"⚠️ Erro OpenWeather ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Erro ao buscar clima: {e}"


# ════════════════════════════════════════════════════════════════
# ESPORTES
# ════════════════════════════════════════════════════════════════

def _espn_fallback() -> str:
    try:
        url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
        r = httpx.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        jogos = []
        for ev in data.get("events", [])[:10]:
            comp = ev.get("competitions", [{}])[0]
            teams = comp.get("competitors", [])
            if len(teams) >= 2:
                home = teams[0]["team"]["name"]
                away = teams[1]["team"]["name"]
                hs = teams[0].get("score", "?")
                aws_ = teams[1].get("score", "?")
                status = comp.get("status", {}).get("type", {}).get("description", "")
                jogos.append(f"⚽ {home} {hs} x {aws_} {away}  _{status}_")
        return "\n".join(jogos) if jogos else "Sem jogos disponíveis."
    except Exception as e:
        return f"⚠️ ESPN falhou: {e}"


@tool
def estatisticas_esportes(esporte: str = "brasileirao") -> str:
    """
    Estatísticas esportivas — times cariocas, Brasileirão, Libertadores, Premier League.
    esporte: flamengo | flu | vasco | botafogo | brasileirao | libertadores | premier | copa_brasil
    Requer FOOTBALL_API_KEY no .env. Sem chave, usa ESPN público.
    """
    esporte = esporte.lower().strip()
    api_key = os.environ.get("FOOTBALL_API_KEY", "").strip()

    if api_key:
        base = "https://v3.football.api-sports.io"
        headers = {"x-apisports-key": api_key}
        league_map = {"brasileirao": 71, "libertadores": 13, "premier": 39, "copa_brasil": 72}
        team_map = {
            "flamengo": 127, "flu": 128, "fluminense": 128, "fluflu": 128,
            "vasco": 130, "botafogo": 131,
        }
        try:
            if esporte in team_map:
                team_id = team_map[esporte]
                url = f"{base}/fixtures?team={team_id}&next=3"
                r = httpx.get(url, headers=headers, timeout=10)
                r.raise_for_status()
                jogos = r.json().get("response", [])
                linhas = [f"⚽ **Próximos jogos — {esporte.capitalize()}**\n"]
                for j in jogos[:3]:
                    dt = j["fixture"]["date"]
                    home = j["teams"]["home"]["name"]
                    away = j["teams"]["away"]["name"]
                    liga = j["league"]["name"]
                    linhas.append(f"📅 {dt[:10]} {dt[11:16]} | {home} x {away} _({liga})_")

                url2 = f"{base}/standings?team={team_id}&season=2026"
                r2 = httpx.get(url2, headers=headers, timeout=10)
                if r2.status_code == 200:
                    st = r2.json().get("response", [])
                    if st:
                        try:
                            team = st[0]["league"]["standings"][0][0]
                            linhas.append(
                                f"\n📊 Brasileirão 2026: {team['rank']}º lugar, "
                                f"{team['points']} pts em {team['all']['played']} jogos"
                            )
                        except (IndexError, KeyError):
                            pass
                return "\n".join(linhas)

            if esporte in league_map:
                league_id = league_map[esporte]
                url = f"{base}/standings?league={league_id}&season=2026"
                r = httpx.get(url, headers=headers, timeout=10)
                r.raise_for_status()
                standings = r.json().get("response", [])
                if not standings:
                    return f"📊 Sem classificação disponível para {esporte} em 2026."
                linhas = [f"📊 **Classificação — {esporte.capitalize()} 2026**\n"]
                try:
                    table = standings[0]["league"]["standings"][0]
                    for i, t in enumerate(table[:10], 1):
                        linhas.append(
                            f"{i:2d}. {t['team']['name']:25s}  "
                            f"{t['points']} pts  ({t['all']['played']}J  "
                            f"{t['all']['win']}V {t['all']['draw']}E {t['all']['lose']}D)"
                        )
                    return "\n".join(linhas)
                except (IndexError, KeyError):
                    return f"⚠️ Formato inesperado de standings para {esporte}"

            return (
                f"⚠️ Esporte '{esporte}' não reconhecido. "
                f"Use: flamengo, flu, vasco, botafogo, brasileirao, libertadores, premier, copa_brasil"
            )
        except httpx.HTTPStatusError as e:
            return f"⚠️ API-Football erro {e.response.status_code}: chave inválida ou limite excedido"
        except Exception as e:
            return f"⚠️ Erro API-Football: {e}\n\nTentando ESPN...\n\n{_espn_fallback()}"

    return (
        f"⚠️ FOOTBALL_API_KEY não configurada — usando ESPN público.\n"
        f"Para dados completos, cadastre-se grátis em https://www.api-football.com\n\n"
        f"📋 **Jogos de hoje (ESPN):**\n\n{_espn_fallback()}"
    )


# ════════════════════════════════════════════════════════════════
# ROTAS
# ════════════════════════════════════════════════════════════════

_BAIRROS_RJ = {
    "copacabana": "Copacabana, Rio de Janeiro, RJ, Brasil",
    "ipanema": "Ipanema, Rio de Janeiro, RJ, Brasil",
    "leblon": "Leblon, Rio de Janeiro, RJ, Brasil",
    "botafogo": "Botafogo, Rio de Janeiro, RJ, Brasil",
    "flamengo": "Flamengo, Rio de Janeiro, RJ, Brasil",
    "lapa": "Lapa, Rio de Janeiro, RJ, Brasil",
    "centro": "Centro, Rio de Janeiro, RJ, Brasil",
    "tijuca": "Tijuca, Rio de Janeiro, RJ, Brasil",
    "barra": "Barra da Tijuca, Rio de Janeiro, RJ, Brasil",
    "urca": "Urca, Rio de Janeiro, RJ, Brasil",
    "catete": "Catete, Rio de Janeiro, RJ, Brasil",
    "laranjeiras": "Laranjeiras, Rio de Janeiro, RJ, Brasil",
    "glória": "Glória, Rio de Janeiro, RJ, Brasil",
    "méier": "Méier, Rio de Janeiro, RJ, Brasil",
    "maracanã": "Maracanã, Rio de Janeiro, RJ, Brasil",
    "recreio": "Recreio dos Bandeirantes, Rio de Janeiro, RJ, Brasil",
    "niterói": "Niterói, RJ, Brasil",
}


def _geocode(endereco: str, api_key: str = "") -> tuple[float, float] | None:
    """Geocodifica endereço → (lat, lon). Mapbox se houver chave, senão Nominatim (OSM)."""
    addr_lower = endereco.lower().strip()
    endereco_busca = _BAIRROS_RJ.get(addr_lower, endereco)
    try:
        if api_key:
            url = (
                f"https://api.mapbox.com/geocoding/v5/mapbox.places/"
                f"{endereco_busca.replace(' ', '%20')}.json?access_token={api_key}&limit=1"
            )
            r = httpx.get(url, timeout=8)
            r.raise_for_status()
            feats = r.json().get("features", [])
            if feats:
                lon, lat = feats[0]["center"]
                return lat, lon
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": endereco_busca, "format": "json", "limit": 1, "countrycodes": "br"},
            headers={"User-Agent": "jarvis-agente/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        log.debug(f"Geocode falhou para '{endereco}': {e}")
    return None


def _is_coord(s: str) -> bool:
    try:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 2:
            float(parts[0])
            float(parts[1])
            return True
    except ValueError:
        pass
    return False


def _parse_coord(s: str) -> tuple[float, float] | None:
    try:
        parts = [p.strip() for p in s.split(",")]
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


@tool
def calcular_rota(origem: str, destino: str, modo: str = "driving") -> str:
    """
    Calcula rota entre dois endereços no Rio de Janeiro.
    modo: driving (carro) | walking (a pé) | cycling (bicicleta).
    Requer MAPBOX_API_KEY para dados completos; sem ela, usa OSRM público.
    """
    api_key = os.environ.get("MAPBOX_API_KEY", "").strip()

    coord_origem = _geocode(origem, api_key) if not _is_coord(origem) else _parse_coord(origem)
    coord_destino = _geocode(destino, api_key) if not _is_coord(destino) else _parse_coord(destino)
    if not coord_origem:
        return f"⚠️ Não encontrei o endereço de origem: '{origem}'"
    if not coord_destino:
        return f"⚠️ Não encontrei o endereço de destino: '{destino}'"

    lat1, lon1 = coord_origem
    lat2, lon2 = coord_destino
    profile = {"driving": "driving", "walking": "walking", "cycling": "cycling"}.get(modo.lower(), "driving")
    modo_label = {"driving": "🚗 Carro", "walking": "🚶 A pé", "cycling": "🚴 Bicicleta"}.get(profile, profile)

    try:
        if api_key:
            url = (
                f"https://api.mapbox.com/directions/v5/mapbox/{profile}/"
                f"{lon1},{lat1};{lon2},{lat2}?steps=true&overview=simplified&geometries=geojson"
                f"&access_token={api_key}"
            )
            r = httpx.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data.get("routes"):
                return f"⚠️ Mapbox não retornou rota para {origem} → {destino}"
            rota = data["routes"][0]
            distancia_km = rota["distance"] / 1000
            duracao_min = rota["duration"] / 60
            steps = rota.get("legs", [{}])[0].get("steps", [])
            instrucoes = [s.get("maneuver", {}).get("instruction", "") for s in steps[:5] if s.get("maneuver", {}).get("instruction")]
            return (
                f"🗺️ **Rota — {modo_label}**\n📍 De: {origem}\n🏁 Até: {destino}\n\n"
                f"📏 Distância: **{distancia_km:.1f} km**\n"
                f"⏱️ Tempo estimado: **{duracao_min:.0f} min**\n\n"
                f"📋 Primeiros passos:\n" + "\n".join(f"  • {i}" for i in instrucoes) + "\n\n"
                f"🗺️ Mapa: https://www.mapbox.com/directions/?router={profile}"
            )
        else:
            url = f"http://router.project-osrm.org/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}?steps=true&overview=false"
            r = httpx.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                return f"⚠️ OSRM não retornou rota para {origem} → {destino}"
            rota = data["routes"][0]
            distancia_km = rota["distance"] / 1000
            duracao_min = rota["duration"] / 60
            steps = rota.get("legs", [{}])[0].get("steps", [])
            instrucoes = []
            for s in steps[:5]:
                m = s.get("maneuver", {}).get("instruction") or f"{s.get('name', '(rua)')} ({s.get('distance', 0):.0f}m)"
                if m:
                    instrucoes.append(m)
            return (
                f"🗺️ **Rota — {modo_label}** (OSRM, sem trânsito real)\n"
                f"📍 De: {origem}\n🏁 Até: {destino}\n\n"
                f"📏 Distância: **{distancia_km:.1f} km**\n"
                f"⏱️ Tempo estimado: **{duracao_min:.0f} min**\n\n"
                f"📋 Primeiros passos:\n" + "\n".join(f"  • {i}" for i in instrucoes) + "\n\n"
                f"💡 Para trânsito em tempo real, cadastre-se grátis em https://www.mapbox.com"
            )
    except httpx.HTTPStatusError as e:
        return f"⚠️ Erro HTTP {e.response.status_code} ao calcular rota: {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ Erro ao calcular rota: {e}"


@tool
def rota_para_destino_favorito(nome_destino: str = "trabalho", modo: str = "driving") -> str:
    """
    Calcula rota da sua casa (DEFAULT_HOME) até um destino favorito
    configurado em FAVORITE_DESTINATIONS no .env.
    """
    favoritos_str = os.environ.get("FAVORITE_DESTINATIONS", "").strip()
    if not favoritos_str:
        return (
            "⚠️ Nenhum destino favorito configurado.\n"
            "Adicione no .env: FAVORITE_DESTINATIONS=Trabalho|R. do Ouvidor, 50;Praia|Av. Atlântica, 1702"
        )
    favoritos = {}
    for item in favoritos_str.split(";"):
        item = item.strip()
        if "|" not in item:
            continue
        nome, end = item.split("|", 1)
        favoritos[nome.strip().lower()] = end.strip()
    destino_endereco = favoritos.get(nome_destino.lower())
    if not destino_endereco:
        lista = "\n".join(f"  • {n}" for n in favoritos.keys())
        return f"⚠️ Destino '{nome_destino}' não está nos favoritos. Disponíveis:\n{lista}"
    return calcular_rota.invoke({
        "origem": DEFAULT_HOME,
        "destino": destino_endereco,
        "modo": modo,
    })


# ════════════════════════════════════════════════════════════════
# COLETA AGENDADA DE NOTÍCIAS
# ════════════════════════════════════════════════════════════════

@tool
def coletar_e_salvar_noticias(quantidade_top: int = 12) -> str:
    """
    Coleta manchetes dos portais configurados, gera resumo via Ollama e salva em
    data/outputs/noticias_AAAAMMDD_HHMM.json. Use quando o usuário pedir panorama de notícias.
    """
    from pathlib import Path as _Path

    if "news_scraper" not in sys.modules:
        import news_scraper  # noqa: F401
    import news_scraper as ns

    try:
        saida = ns.coletar_e_enviar()
        OUTPUT_DIR = _Path(os.environ.get("DATA_OUTPUTS_PATH", "data/outputs"))
        arquivos = sorted(OUTPUT_DIR.glob("noticias_*.json"), reverse=True)
        arq = arquivos[0] if arquivos else None
        top = saida.get("manchetes_unicas", [])[:5]
        top_str = "\n".join(f"{i+1}. {m}" for i, m in enumerate(top))
        msg = (
            f"📋 Coleta concluída — {saida['portais_ok']}/{saida['portais_total']} portais\n"
            f"🆔 Coleta ID: `{saida.get('coleta_id', '?')}`\n"
            f"💾 Salvo em: {arq}\n\n🔝 TOP 5:\n{top_str}\n\n"
        )
        if saida.get("resumo_geral"):
            msg += f"💡 Resumo: {saida['resumo_geral']}\n"
        return msg
    except Exception as e:
        return f"⚠️ Erro ao coletar notícias: {e}"


@tool
def agendar_coleta_automatica(ativar: bool = True) -> str:
    """
    Ativa/desativa o agendamento automático de coleta (4x/dia nos horários do .env).
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        return "⚠️ Instale apscheduler: pip install apscheduler"

    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)

    if ativar:
        if _scheduler.running:
            return "⏰ Agendamento já está ativo."
        horarios = [
            os.getenv("NEWS_SCHEDULE_MORNING", "08:00"),
            os.getenv("NEWS_SCHEDULE_NOON", "12:00"),
            os.getenv("NEWS_SCHEDULE_AFTERNOON", "18:00"),
            os.getenv("NEWS_SCHEDULE_NIGHT", "21:00"),
        ]
        for h in horarios:
            try:
                hh, mm = h.split(":")
                _scheduler.add_job(
                    coletar_e_salvar_noticias.fn, "cron",
                    hour=int(hh), minute=int(mm),
                    id=f"coleta_{h}", replace_existing=True,
                )
            except Exception as e:
                log.warning(f"Horário inválido {h}: {e}")
        _scheduler.start()
        return f"⏰ Agendamento ativado: {', '.join(horarios)}"
    else:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            return "⏰ Agendamento desativado."
        return "⏰ Agendamento já estava desativado."


# ════════════════════════════════════════════════════════════════
# GOOGLE CALENDAR + GMAIL (wrappers finos)
# ════════════════════════════════════════════════════════════════

@tool
def listar_eventos_google(periodo: str = "hoje") -> str:
    """Lista eventos do Google Calendar.
    periodo: hoje | amanha | semana | proximos7.
    Requer credentials/google_credentials.json."""
    return gs.listar_eventos(periodo=periodo)


@tool
def buscar_eventos_google(termo: str) -> str:
    """Busca eventos no Google Calendar por palavra-chave."""
    return gs.buscar_eventos(termo=termo)


@tool
def criar_evento_google(titulo: str, inicio: str, duracao_minutos: int = 60,
                         descricao: str = "", local: str = "") -> str:
    """Cria um evento no Google Calendar.
    inicio: ISO 8601 ('2026-06-23T15:00') ou 'YYYY-MM-DD' pra dia inteiro."""
    return gs.criar_evento(
        titulo=titulo, inicio=inicio, duracao_minutos=duracao_minutos,
        descricao=descricao, local=local,
    )


@tool
def buscar_emails_gmail(termo: str = "", max_resultados: int = 5,
                         apenas_nao_lidos: bool = False) -> str:
    """Busca e-mails no Gmail por palavra-chave.
    apenas_nao_lidos=True filtra não lidos."""
    return gs.buscar_emails(
        termo=termo, max_resultados=max_resultados, apenas_nao_lidos=apenas_nao_lidos,
    )


@tool
def ler_email_gmail(mensagem_id: str) -> str:
    """Lê o conteúdo completo de um e-mail pelo ID do Gmail."""
    return gs.ler_email(mensagem_id=mensagem_id)


@tool
def classificar_inbox_gmail(max_resultados: int = 10) -> str:
    """Lê os últimos e-mails da INBOX e aplica a classificação automática do jarvis."""
    return gs.classificar_inbox(max_resultados=max_resultados)


@tool
def enviar_email_gmail(para: str, assunto: str, corpo: str) -> str:
    """Envia um e-mail via Gmail (requer scope gmail.send configurado)."""
    return gs.enviar_email(para=para, assunto=assunto, corpo=corpo)


# ════════════════════════════════════════════════════════════════
# Lista única de tools — importada pelo agent.py
# ════════════════════════════════════════════════════════════════

ALL_TOOLS = [
    buscar_noticias_rj_brasil,
    buscar_bolsa_valores,
    classificar_email,
    analisar_investimentos,
    coletar_e_salvar_noticias,
    agendar_coleta_automatica,
    clima_rio_janeiro,
    estatisticas_esportes,
    calcular_rota,
    rota_para_destino_favorito,
    listar_eventos_google,
    buscar_eventos_google,
    criar_evento_google,
    buscar_emails_gmail,
    ler_email_gmail,
    classificar_inbox_gmail,
    enviar_email_gmail,
]