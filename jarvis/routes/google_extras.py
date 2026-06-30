"""routes/google_extras.py — Endpoints diretos (sem LLM) para Calendar/Gmail.

Pensado pra integração programática (mobile, CLI, webhooks).
O chat principal continua usando o tool `gerenciar_agenda_gmail`.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..tools.google import gerenciar_agenda_gmail

log = logging.getLogger(__name__)
bp = Blueprint("google_extras", __name__)


@bp.route("/api/agenda")
def api_agenda():
    periodo = request.args.get("periodo", "hoje")
    dados = gerenciar_agenda_gmail.invoke({"acao": "listar_eventos", "periodo": periodo})
    return jsonify({"dados": dados})


@bp.route("/api/emails")
def api_emails():
    termo = request.args.get("termo", "")
    apenas_nao_lidos = request.args.get("nao_lidos", "0") == "1"
    dados = gerenciar_agenda_gmail.invoke({
        "acao": "buscar_emails",
        "termo": termo,
        "apenas_nao_lidos": apenas_nao_lidos,
        "max_resultados": 5,
    })
    return jsonify({"dados": dados})
