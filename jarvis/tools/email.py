"""tools/email.py — Classificador local de e-mails (regex, sem LLM).

Rápido e determinístico — economiza tokens do LLM principal.
"""

from __future__ import annotations

from langchain_core.tools import tool

_KEYWORDS_URGENTE   = ("urgente", "prazo", "vencimento", "imediato", "deadline", "asap")
_KEYWORDS_FINANCEIRO = ("fatura", "boleto", "pix", "pagamento", "cobrança", "débito", "nota fiscal")
_KEYWORDS_SPAM       = ("oferta", "promoção", "desconto", "grátis", "clique aqui", "ganhe", "compre")
_KEYWORDS_TRABALHO   = ("reunião", "meeting", "proposta", "projeto", "contrato", "cliente")
_KEYWORDS_PESSOAL    = ("família", "amigo", "feliz", "aniversário", "pessoal")


def _match_any(texto: str, palavras: tuple[str, ...]) -> bool:
    return any(w in texto for w in palavras)


@tool
def classificar_email(conteudo_email: str) -> str:
    """Classifica um e-mail em categorias (urgente, financeiro, spam, trabalho, pessoal)
    e sugere ação. Recebe o texto completo do e-mail como entrada."""
    if not conteudo_email or not conteudo_email.strip():
        return "📋 GERAL/INFORMATIVO — entrada vazia, nada a classificar"

    txt = conteudo_email.lower()
    cats: list[str] = []

    if _match_any(txt, _KEYWORDS_URGENTE):
        cats.append("🚨 URGENTE")
    if _match_any(txt, _KEYWORDS_FINANCEIRO):
        cats.append("💳 FINANCEIRO")
    if _match_any(txt, _KEYWORDS_SPAM):
        cats.append("🗑️ SPAM/MARKETING")
    if _match_any(txt, _KEYWORDS_TRABALHO):
        cats.append("💼 TRABALHO")
    if _match_any(txt, _KEYWORDS_PESSOAL):
        cats.append("👤 PESSOAL")
    if not cats:
        cats.append("📋 GERAL/INFORMATIVO")

    return f"Categorias detectadas: {', '.join(cats)}"
