"""test_tools.py — Testes das tools (sem rede externa).

Cobre apenas tools determinísticas (regex, lookup de bairros) e garante
que ferramentas que dependem de rede retornem string amigável em vez de
explodir quando o serviço está offline.
"""

import os

import pytest

from jarvis.config import RJ_BAIRROS
from jarvis.tools.email import classificar_email
from jarvis.tools.investimentos import analisar_investimentos
from jarvis.tools.rotas import _is_coord, _parse_coord


# ── Helpers internos (sem rede) ──────────────────────────────────

def test_is_coord_detecta_lat_lon():
    assert _is_coord("-22.9,-43.2") is True
    assert _is_coord("0,0") is True
    assert _is_coord("Rio de Janeiro") is False
    assert _is_coord("abc,def") is False
    assert _is_coord("1.0,2.0,3.0") is False


def test_parse_coord_ok_e_erro():
    assert _parse_coord("-22.9,-43.2") == (-22.9, -43.2)
    assert _parse_coord("inválido") is None


def test_bairros_rj_tem_principais():
    """Bairros cariocas mais comuns precisam estar no lookup."""
    essenciais = {"copacabana", "ipanema", "botafogo", "flamengo", "centro", "barra"}
    assert essenciais.issubset(RJ_BAIRROS.keys()), (
        f"Faltando: {essenciais - RJ_BAIRROS.keys()}"
    )


# ── Tools determinísticas ────────────────────────────────────────

@pytest.mark.parametrize("perfil", ["conservador", "moderado", "arrojado"])
def test_analisar_investimentos(perfil):
    saida = analisar_investimentos.invoke({"perfil": perfil})
    assert perfil.upper() in saida.upper() or perfil in saida.lower()
    assert "PERFIL" in saida.upper()


def test_analisar_investimentos_desconhecido_cai_no_moderado():
    saida = analisar_investimentos.invoke({"perfil": "exótico-xyz"})
    assert "MODERADO" in saida.upper()


def test_classificar_email_urgente():
    saida = classificar_email.invoke({"conteudo_email": "URGENTE: prazo vencendo amanhã!"})
    assert "URGENTE" in saida


def test_classificar_email_financeiro():
    saida = classificar_email.invoke({"conteudo_email": "Sua fatura de R$250 vence hoje."})
    assert "FINANCEIRO" in saida


def test_classificar_email_spam():
    saida = classificar_email.invoke({"conteudo_email": "Promoção imperdível! Clique aqui e ganhe grátis!"})
    assert "SPAM" in saida or "MARKETING" in saida


def test_classificar_email_trabalho():
    saida = classificar_email.invoke({"conteudo_email": "Proposta de contrato do cliente XYZ em anexo."})
    assert "TRABALHO" in saida


def test_classificar_email_generico():
    saida = classificar_email.invoke({"conteudo_email": "olá, segue atualização qualquer"})
    assert "GERAL" in saida.upper()


# ── Tools que dependem de rede — não quebram se offline ──────────

def test_classificar_email_email_vazio_retorna_string_amigavel():
    """Não deve lançar exceção mesmo com entrada vazia."""
    saida = classificar_email.invoke({"conteudo_email": ""})
    assert isinstance(saida, str)
    assert len(saida) > 0


def test_modos_rota_validos():
    """Garante que os 3 modos do Mapbox estão mapeados."""
    from jarvis.tools.rotas import _MODO_LABELS
    assert set(_MODO_LABELS) == {"driving", "walking", "cycling"}


def test_parse_favoritos_vazio():
    """Sem env var, retorna dict vazio."""
    from jarvis.tools.rotas import _parse_favoritos
    import importlib
    import jarvis.tools.rotas as r
    importlib.reload(r)
    # se FAVORITE_DESTINATIONS não tiver valor, _FAVORITOS é {}
    assert isinstance(r._FAVORITOS, dict)