"""tools/noticias.py — Coleta e sumarização de notícias do RJ/Brasil.

Consolida `buscar_noticias_rj_brasil` + `coletar_e_salvar_noticias` em
UMA tool (`buscar_panorama_rj`) que decide automaticamente se vai só
retornar manchetes ou se vai persistir.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

import httpx
from langchain_core.tools import tool

log = logging.getLogger(__name__)


@tool
def buscar_panorama_rj(tema: str = "geral", persistir: bool = False) -> str:
    """Busca um panorama de notícias do Rio de Janeiro e do Brasil em 17 portais
    (RSS + HTML, deduplicado). Use para perguntas como 'quais são as notícias',
    'manchetes de hoje', 'o que está acontecendo no Rio'.

    Args:
        tema: filtro genérico (atualmente 'geral' cobre todos).
        persistir: se True, salva JSON em data/outputs e gera resumo via Ollama.
    """
    if "news_scraper" not in sys.modules:
        try:
            import news_scraper  # noqa: F401
        except ImportError as e:
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

        cabecalho = f"\n".join(f"• {m}" for m in manchetes[:25])

        if persistir:
            try:
                saida = ns.coletar_e_enviar()
                arquivos = sorted(
                    Path(os.environ.get("DATA_OUTPUTS_PATH", "data/outputs")).glob("noticias_*.json"),
                    reverse=True,
                )
                resumo = saida.get("resumo_geral", "")
                return (
                    cabecalho
                    + "\n\n---\n💾 Coleta persistida em "
                    + str(arquivos[0] if arquivos else "?")
                    + (f"\n💡 Resumo: {resumo}" if resumo else "")
                )
            except Exception as e:
                log.warning("persistir falhou: %s", e)
                return cabecalho

        return cabecalho

    except Exception as e:
        # Fallback RSS simples (uma chamada só)
        try:
            r = httpx.get(
                "https://g1.globo.com/rss/g1/rio-de-janeiro/",
                timeout=8,
                follow_redirects=True,
            )
            titulos = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)[:8]
            if titulos:
                return "\n".join(f"• [G1 Rio] {t.strip()}" for t in titulos)
        except Exception:
            pass
        return f"⚠️ Erro ao buscar notícias: {e}"
