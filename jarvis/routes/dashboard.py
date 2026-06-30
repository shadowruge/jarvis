"""routes/dashboard.py — Cards do dashboard (chamadas diretas a tools, sem LLM)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..tools.bolsa import dados_bolsa
from ..tools.clima import clima_atual_e_previsao
from ..tools.esportes import esportes_cariocas
from ..tools.investimentos import analisar_investimentos
from ..tools.noticias import buscar_panorama_rj
from ..tools.rotas import calcular_rota_rio

log = logging.getLogger(__name__)

bp = Blueprint("dashboard", __name__)


@bp.route("/api/bolsa")
def api_bolsa():
    return jsonify({"dados": dados_bolsa.invoke({})})


@bp.route("/api/noticias")
def api_noticias():
    tema = request.args.get("tema", "geral")
    return jsonify({"dados": buscar_panorama_rj.invoke({"tema": tema})})


@bp.route("/api/investimentos")
def api_investimentos():
    perfil = request.args.get("perfil", "moderado")
    return jsonify({"dados": analisar_investimentos.invoke({"perfil": perfil})})


@bp.route("/api/clima")
def api_clima():
    previsao = request.args.get("previsao", "atual")
    return jsonify({"dados": clima_atual_e_previsao.invoke({"previsao": previsao})})


@bp.route("/api/esportes")
def api_esportes():
    esporte = request.args.get("esporte", "brasileirao")
    return jsonify({"dados": esportes_cariocas.invoke({"esporte": esporte})})


@bp.route("/api/rota")
def api_rota():
    origem = request.args.get("origem", "")
    destino = request.args.get("destino", "")
    modo = request.args.get("modo", "driving")
    nome_destino = request.args.get("nome_destino", "")

    if not destino and not nome_destino:
        return jsonify({"erro": "destino ou nome_destino é obrigatório"}), 400

    return jsonify({
        "dados": calcular_rota_rio.invoke({
            "origem": origem, "destino": destino,
            "modo": modo, "nome_destino": nome_destino,
        })
    })
