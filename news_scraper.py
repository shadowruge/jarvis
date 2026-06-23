"""
news_scraper.py v2 — Scraping de 20 portais do Rio + Brasil.

Melhorias:
  - httpx async com semáforo de concorrência (mais rápido)
  - Fallback RSS → scraping HTML → links <a>
  - Deduplicação por similaridade (distância de Levenshtein simples)
  - Score de relevância por portal (peso configurable)
  - Resumo via Ollama com retry e timeout adequado
  - Resumo geral consolidado com TOP-5 manchetes do dia
  - Agendamento automático via schedule (4x/dia)
  - Salva resultado em data/outputs/noticias_YYYYMMDD.json
  - Log estruturado + estatísticas ao final
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import uuid
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ────────────────────────────────────────────────────
log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [news] %(message)s",
    datefmt="%H:%M:%S",
)

# ─── Configurações ───────────────────────────────────────────────
OLLAMA_URL       = (os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
OLLAMA_MODEL     = (os.getenv("OLLAMA_MODEL") or "minimax-m3:cloud").strip()
SAVE_OUTPUTS     = os.getenv("SAVE_OUTPUTS", "true").lower() == "true"
OUTPUT_DIR       = Path(os.getenv("DATA_OUTPUTS_PATH", "data/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_PORTAIS_CONCORRENTES = 6   # semáforo de concorrência HTTP
MAX_MANCHETES_POR_PORTAL = 4
TIMEOUT_HTTP = 12              # segundos
TIMEOUT_OLLAMA = 45

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Portais com peso e RSS opcional ────────────────────────────
# peso: 3 = grande mídia, 2 = mídia regional relevante, 1 = mídia local/comunitária
# rss: quando existe, é tentado antes do scraping HTML (mais rápido e limpo)
PORTAIS: list[dict] = [
    {"nome": "G1 Rio",            "url": "https://g1.globo.com/rj/rio-de-janeiro/",      "peso": 3,
     "rss": "https://g1.globo.com/rss/g1/rio-de-janeiro/"},
    {"nome": "O Globo",           "url": "https://oglobo.globo.com/rio/",                "peso": 3,
     "rss": "https://oglobo.globo.com/rss.xml"},
    {"nome": "Extra",             "url": "https://extra.globo.com/noticias/rio/",        "peso": 3,
     "rss": "https://g1.globo.com/rss/g1/rio-de-janeiro/"},
    {"nome": "O Dia",             "url": "https://odia.ig.com.br/rio-de-janeiro",        "peso": 2},
    {"nome": "Meia Hora",         "url": "https://www.meiahora.com.br/geral/rio-de-janeiro", "peso": 2},
    {"nome": "Diário do Rio",     "url": "https://diariodorio.com",                      "peso": 2},
    {"nome": "Enfoco",            "url": "https://enfoco.com.br",                        "peso": 2},
    {"nome": "Jornal do Brasil",  "url": "https://www.jb.com.br/rio",                    "peso": 2},
    {"nome": "O Fluminense",      "url": "https://www.ofluminense.com.br/editorias/cidades", "peso": 2},
    {"nome": "O São Gonçalo",     "url": "https://www.osaogoncalo.com.br",               "peso": 1},
    {"nome": "Voz das Comunidades","url": "https://vozdascomunidades.com.br",            "peso": 2},
    {"nome": "Mare Online",       "url": "https://mareonline.com.br",                    "peso": 1},
    {"nome": "Notícia Preta",     "url": "https://noticiapreta.com.br",                  "peso": 2},
    {"nome": "Correio da Manhã",  "url": "https://jornalcorreiodamanha.com.br",          "peso": 1},
    {"nome": "Jornal da Barra",   "url": "https://www.jornaldabarra.com.br",             "peso": 1},
    {"nome": "Posto Seis",        "url": "https://www.postoseis.com.br",                 "peso": 1},
    {"nome": "RJ Agora",          "url": "https://rjagora.com.br",                       "peso": 1},
]

# UUID v5 fixo por portal (namespace determinístico + nome do portal)
# Garante que o mesmo portal sempre tenha o mesmo ID em qualquer coleta
_PORTAL_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
PORTAL_IDS: dict[str, str] = {
    nome: str(uuid.uuid5(_PORTAL_NAMESPACE, f"jarvis.portal.{nome}"))
    for nome in (p["nome"] for p in PORTAIS)
}

IGNORAR_FRASES = {
    "siga", "redes sociais", "newsletter", "assine", "cadastre",
    "publicidade", "clique aqui", "veja também", "leia mais",
    "sign in", "log in", "subscribe", "cookies", "privacy",
    "aceitar", "termos de uso", "política", "voltar ao topo",
    "highway", "warmer", "everything you need", "hay fever",
}


# ─── Helpers ─────────────────────────────────────────────────────
def _normalizar(texto: str) -> str:
    """Lowercase + remove acentos + colapsa espaços."""
    s = unicodedata.normalize("NFD", texto.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _similar(a: str, b: str, threshold: float = 0.75) -> bool:
    """Verifica se duas manchetes são similares (Jaccard de bigramas)."""
    def bigramas(s: str) -> set[str]:
        s = _normalizar(s)
        return {s[i:i+2] for i in range(len(s) - 1)}
    ba, bb = bigramas(a), bigramas(b)
    if not ba or not bb:
        return False
    jac = len(ba & bb) / len(ba | bb)
    return jac >= threshold


def _e_manchete_valida(texto: str) -> bool:
    if not (25 < len(texto) < 250):
        return False
    tl = texto.lower()
    if any(ig in tl for ig in IGNORAR_FRASES):
        return False
    # Deve ter pelo menos uma vogal com acento ou letra portuguesa
    if not re.search(r"[áéíóúãõâêîôûàèç]", texto, re.I):
        # Aceita se tiver pelo menos 3 vogais simples (textos em pt sem acentos)
        if len(re.findall(r"[aeiou]", texto, re.I)) < 4:
            return False
    return True


def _deduplicar(manchetes: list[str]) -> list[str]:
    """Remove manchetes duplicadas ou muito similares."""
    resultado: list[str] = []
    for m in manchetes:
        if not any(_similar(m, r) for r in resultado):
            resultado.append(m)
    return resultado


# ─── Extração RSS ────────────────────────────────────────────────
def _extrair_rss(url_rss: str) -> list[str]:
    try:
        r = httpx.get(url_rss, headers=HEADERS, timeout=TIMEOUT_HTTP, follow_redirects=True)
        # CDATA
        itens = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)
        if not itens:
            itens = re.findall(r"<title>(.*?)</title>", r.text)
            itens = itens[1:]   # remove título do canal
        return [t.strip() for t in itens if _e_manchete_valida(t.strip())]
    except Exception as e:
        log.debug(f"RSS {url_rss}: {e}")
        return []


# ─── Extração HTML ───────────────────────────────────────────────
def _extrair_html(url: str) -> list[str]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=TIMEOUT_HTTP, follow_redirects=True)
        # Corrige encoding
        if r.encoding and r.encoding.lower() in ("iso-8859-1", "latin-1", "windows-1252"):
            html = r.content.decode("utf-8", errors="ignore")
        else:
            html = r.text

        soup = BeautifulSoup(html, "lxml")
        manchetes: list[str] = []

        # 1ª tentativa: headings
        for tag in soup.find_all(["h1", "h2", "h3"]):
            t = tag.get_text(" ", strip=True)
            if _e_manchete_valida(t):
                manchetes.append(t)

        # 2ª tentativa: links com texto longo
        if len(manchetes) < 2:
            for a in soup.find_all("a", href=True):
                t = a.get_text(" ", strip=True)
                if _e_manchete_valida(t):
                    manchetes.append(t)

        return manchetes
    except Exception as e:
        log.debug(f"HTML {url}: {e}")
        return []


# ─── Por portal ──────────────────────────────────────────────────
def _manchete_id(texto: str) -> str:
    """UUID v5 determinístico baseado no texto da manchete (mesmo texto = mesmo id)."""
    return str(uuid.uuid5(_PORTAL_NAMESPACE, f"jarvis.manchete.{texto.strip()}"))


async def _raspar_portal(portal: dict, sem: asyncio.Semaphore) -> dict:
    """Raspa um portal e retorna resultado estruturado."""
    async with sem:
        loop = asyncio.get_event_loop()
        nome = portal["nome"]
        manchetes: list[str] = []

        # Tenta RSS primeiro (mais limpo)
        if portal.get("rss"):
            manchetes = await loop.run_in_executor(None, _extrair_rss, portal["rss"])

        # Fallback HTML
        if not manchetes:
            manchetes = await loop.run_in_executor(None, _extrair_html, portal["url"])

        manchetes = _deduplicar(manchetes)[:MAX_MANCHETES_POR_PORTAL]

        log.info(f"  {'✅' if manchetes else '❌'} {nome}: {len(manchetes)} manchete(s)")
        return {
            "portal": nome,
            "portal_id": PORTAL_IDS.get(nome, ""),
            "peso": portal["peso"],
            "manchetes": manchetes,
            "manchetes_ids": [_manchete_id(m) for m in manchetes],
        }


# ─── Resumo Ollama ───────────────────────────────────────────────
def _resumir(manchetes: list[str], contexto: str = "") -> str:
    if not manchetes:
        return ""
    texto = "\n".join(f"- {m}" for m in manchetes[:8])
    prompt = (
        f"Você é um jornalista brasileiro conciso. "
        f"{'Contexto: ' + contexto + '. ' if contexto else ''}"
        f"Com base nestas manchetes, escreva UM parágrafo curto (2-3 frases) "
        f"em português brasileiro resumindo os principais temas:\n{texto}\n\nResumo:"
    )
    for tentativa in range(2):
        try:
            r = httpx.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 120, "num_ctx": 1024},
                },
                timeout=TIMEOUT_OLLAMA,
            )
            r.raise_for_status()
            txt = r.json()["message"]["content"].strip()
            txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()
            txt = re.sub(r"^(resumo:|summary:)\s*", "", txt, flags=re.I).strip()
            return txt
        except Exception as e:
            log.warning(f"Ollama tentativa {tentativa+1}: {e}")
    return ""


# ─── Helpers de formatação ───────────────────────────────────────
def _esc(s: str) -> str:
    return s.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")


# ─── Pipeline principal ──────────────────────────────────────────
async def _pipeline_async() -> dict:
    agora   = datetime.now()
    periodo = _periodo_do_dia(agora.hour)
    sem     = asyncio.Semaphore(MAX_PORTAIS_CONCORRENTES)

    log.info(f"🚀 Iniciando coleta — {agora.strftime('%d/%m/%Y %H:%M')} ({periodo})")

    tarefas = [_raspar_portal(p, sem) for p in PORTAIS]
    resultados = await asyncio.gather(*tarefas, return_exceptions=True)

    portais_ok: list[dict] = []
    todas_manchetes_ponderadas: list[tuple[str, int]] = []  # (manchete, peso)

    for res in resultados:
        if isinstance(res, Exception):
            log.error(f"Tarefa falhou: {res}")
            continue
        if res["manchetes"]:
            portais_ok.append(res)
            for m in res["manchetes"]:
                todas_manchetes_ponderadas.append((m, res["peso"]))

    # ── Envia por portal ─────────────────────────────────────────
    for item in portais_ok:
        linhas = "\n".join(f"• {_esc(m)}" for m in item["manchetes"])
        msg    = f"🗞 *{_esc(item['portal'])}*\n{linhas}\n"

        # Resumo para portais com peso ≥ 2
        if item["peso"] >= 2 and len(item["manchetes"]) >= 2:
            resumo = _resumir(item["manchetes"], contexto=item["portal"])
            if resumo:
                msg += f"💡 _{_esc(resumo)}_\n"

        log.info(f"🗞  {item['portal']}: {len(item['manchetes'])} manchete(s)")

    # ── TOP manchetes ponderadas (mais importantes) ──────────────
    # Ordena por peso e deduplicação global
    manchetes_ordenadas = [m for m, _ in sorted(todas_manchetes_ponderadas, key=lambda x: -x[1])]
    manchetes_unicas    = _deduplicar(manchetes_ordenadas)[:12]

    # Resumo geral do dia
    log.info("🤖 Gerando resumo geral...")
    resumo_geral = _resumir(
        manchetes_unicas[:8],
        contexto="principais manchetes do Rio de Janeiro e Brasil"
    )

    top5 = "\n".join(f"{i+1}. {_esc(m)}" for i, m in enumerate(manchetes_unicas[:5]))
    msg_final = (
        f"📋 *TOP 5 Manchetes do Dia*\n{top5}\n"
        + (f"\n💡 *Resumo Geral:*\n_{_esc(resumo_geral)}_\n" if resumo_geral else "")
        + f"\n✅ {len(portais_ok)}/{len(PORTAIS)} portais coletados."
    )
    log.info(f"📋 TOP 5: {top5}")
    if resumo_geral:
        log.info(f"💡 Resumo geral: {resumo_geral}")

    # ── Salva JSON ───────────────────────────────────────────────
    coleta_id = str(uuid.uuid4())  # UUID v4 aleatório — identifica esta execução

    # Monta lista global com IDs (manchete → portal_origem → id)
    manchetes_global = []
    for item in portais_ok:
        for m, mid in zip(item["manchetes"], item.get("manchetes_ids", [])):
            manchetes_global.append({
                "id": mid,
                "manchete": m,
                "portal": item["portal"],
                "portal_id": item.get("portal_id", ""),
                "peso": item["peso"],
            })

    # Ordena por peso desc e deduplica por id (manchetes iguais em portais diferentes viram 1)
    vistos = set()
    manchetes_unicas_full = []
    for item in sorted(manchetes_global, key=lambda x: -x["peso"]):
        if item["id"] in vistos:
            continue
        vistos.add(item["id"])
        manchetes_unicas_full.append(item)
    manchetes_unicas_full = manchetes_unicas_full[:12]

    saida = {
        "coleta_id": coleta_id,
        "data": agora.isoformat(),
        "periodo": periodo,
        "portais_ok": len(portais_ok),
        "portais_total": len(PORTAIS),
        "portais": [{"nome": p["portal"], "portal_id": p.get("portal_id", ""), "peso": p["peso"]}
                    for p in portais_ok],
        "manchetes_unicas": [m["manchete"] for m in manchetes_unicas_full],
        "manchetes": manchetes_unicas_full,
        "resumo_geral": resumo_geral,
        "detalhes": portais_ok,
    }
    if SAVE_OUTPUTS:
        arq = OUTPUT_DIR / f"noticias_{agora.strftime('%Y%m%d_%H%M')}.json"
        arq.write_text(json.dumps(saida, ensure_ascii=False, indent=2))
        log.info(f"📄 Salvo em {arq} (coleta_id={coleta_id})")

    log.info(f"✅ Concluído! {len(portais_ok)}/{len(PORTAIS)} portais. "
             f"{len(manchetes_unicas_full)} manchetes únicas.")
    return saida


def _periodo_do_dia(hora: int) -> str:
    if hora < 12: return "Edição Matinal ☀️"
    if hora < 15: return "Edição do Meio-Dia 🌤"
    if hora < 19: return "Edição da Tarde 🌆"
    return "Edição Noturna 🌙"


def coletar_e_enviar() -> dict:
    """Ponto de entrada síncrono. Executa o pipeline async."""
    return asyncio.run(_pipeline_async())


# ─── Agendamento ─────────────────────────────────────────────────
def iniciar_agendador():
    """
    Agenda coletas automáticas conforme .env:
      NEWS_SCHEDULE_MORNING / NOON / AFTERNOON / NIGHT
    Requer: pip install schedule
    """
    try:
        import schedule
        import time
    except ImportError:
        log.error("Instale 'schedule': pip install schedule")
        return

    horarios = [
        os.getenv("NEWS_SCHEDULE_MORNING",   "08:00"),
        os.getenv("NEWS_SCHEDULE_NOON",      "12:00"),
        os.getenv("NEWS_SCHEDULE_AFTERNOON", "18:00"),
        os.getenv("NEWS_SCHEDULE_NIGHT",     "21:00"),
    ]

    for h in horarios:
        schedule.every().day.at(h).do(coletar_e_enviar)
        log.info(f"⏰ Agendado para {h}")

    log.info("📅 Agendador iniciado. Pressione Ctrl+C para parar.")
    # Coleta imediata ao iniciar
    coletar_e_enviar()
    while True:
        schedule.run_pending()
        time.sleep(30)


# ─── CLI ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "agora"
    if modo == "agendar":
        iniciar_agendador()
    else:
        resultado = coletar_e_enviar()
        print(f"\n📊 Resumo: {resultado['portais_ok']}/{resultado['portais_total']} portais")
        print(f"📌 {len(resultado['manchetes_unicas'])} manchetes únicas coletadas")
