"""test_tools.py — Testes das tools (sem rede externa).

Cobre apenas tools determinísticas (regex, lookup de bairros) e garante
que ferramentas que dependem de rede retornem string amigável em vez de
explodir quando o serviço está offline.
"""

import os

import pytest

from tools import (
    _BAIRROS_RJ,
    _geocode,
    _is_coord,
    _parse_coord,
    analisar_investimentos,
    classificar_email,
)


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
    assert essenciais.issubset(_BAIRROS_RJ.keys()), (
        f"Faltando: {essenciais - _BAIRROS_RJ.keys()}"
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


# ── Geocode: Nominatim público (pode falhar em CI sem rede) ─────

@pytest.mark.skipif(
    "GITHUB_ACTIONS" in os.environ,
    reason="Nominatim não é confiável em CI (rate limit)",
)
def test_geocode_bairro_rio_retorna_tuple():
    """Bairro conhecido do Rio deve resolver pra coordenadas no Brasil."""
    coord = _geocode("Copacabana", api_key="")
    if coord is not None:  # pode falhar offline
        lat, lon = coord
        assert -24 < lat < -22
        assert -44 < lon < -43