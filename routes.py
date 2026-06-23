"""
routes.py — Todas as rotas Flask (cards do dashboard + chat).

Dividido em 3 blocos:
  - Cards (rotas /api/* rápidas, sem LLM): pra carregar dados no dashboard
  - Chat (rotas /chat e /chat/stream): interação principal com o agente
  - Auxiliares (/, /api/info): home e healthcheck

Cada rota é uma função fina que delega pros tools (tools.py) ou pro agente (agent.py).
"""

from __future__ import annotations

import json as _json
import logging
import os
import re
import uuid

from flask import jsonify, render_template, request, session
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agent import OLLAMA_HOST, OLLAMA_MODEL, SYSTEM_PROMPT, agente
from tools import (
    agendar_coleta_automatica,
    analisar_investimentos,
    buscar_bolsa_valores,
    buscar_emails_gmail,
    buscar_eventos_google,
    buscar_noticias_rj_brasil,
    classificar_email,
    classificar_inbox_gmail,
    clima_rio_janeiro,
    coletar_e_salvar_noticias,
    criar_evento_google,
    estatisticas_esportes,
    listar_eventos_google,
    rota_para_destino_favorito,
)

log = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 2000


def register_routes(app):

    # ══════════════════════════════════════════════════════════
    # Home + info
    # ══════════════════════════════════════════════════════════

    @app.route("/")
    def home():
        return render_template("index.html", ollama_model=OLLAMA_MODEL)

    @app.route("/api/info")
    def api_info():
        return jsonify({"modelo": OLLAMA_MODEL, "host": OLLAMA_HOST})

    # ══════════════════════════════════════════════════════════
    # Cards do dashboard (chamadas diretas às tools, sem LLM)
    # ══════════════════════════════════════════════════════════

    @app.route("/api/bolsa")
    def api_bolsa():
        return jsonify({"dados": buscar_bolsa_valores.invoke({})})

    @app.route("/api/noticias")
    def api_noticias():
        tema = request.args.get("tema", "geral")
        return jsonify({"dados": buscar_noticias_rj_brasil.invoke({"tema": tema})})

    @app.route("/api/investimentos")
    def api_investimentos():
        perfil = request.args.get("perfil", "moderado")
        return jsonify({"dados": analisar_investimentos.invoke({"perfil": perfil})})

    @app.route("/api/coletar", methods=["POST"])
    def api_coletar():
        return jsonify({"dados": coletar_e_salvar_noticias.invoke({"quantidade_top": 12})})

    @app.route("/api/agendar", methods=["POST"])
    def api_agendar():
        dados = request.get_json(silent=True) or {}
        ativar = bool(dados.get("ativar", True))
        return jsonify({"dados": agendar_coleta_automatica.invoke({"ativar": ativar})})

    @app.route("/api/clima", methods=["GET"])
    def api_clima():
        previsao = request.args.get("previsao", "atual")
        return jsonify({"dados": clima_rio_janeiro.invoke({"previsao": previsao})})

    @app.route("/api/esportes", methods=["GET"])
    def api_esportes():
        esporte = request.args.get("esporte", "brasileirao")
        return jsonify({"dados": estatisticas_esportes.invoke({"esporte": esporte})})

    @app.route("/api/rota", methods=["GET"])
    def api_rota():
        origem  = request.args.get("origem", "")
        destino = request.args.get("destino", "")
        modo    = request.args.get("modo", "driving")
        if not origem or not destino:
            return jsonify({"erro": "origem e destino são obrigatórios"}), 400
        return jsonify({
            "dados": rota_para_destino_favorito.invoke({"nome_destino": destino, "modo": modo})
            if destino.lower() in {"trabalho", "casa", "aeroporto"}
            else _calc_rota_direta(origem, destino, modo)
        })

    @app.route("/api/rota/favorito/<nome>", methods=["GET"])
    def api_rota_favorito(nome):
        try:
            modo = request.args.get("modo", "driving")
            dados = rota_para_destino_favorito.invoke({"nome_destino": nome, "modo": modo})
            return jsonify({"dados": dados})
        except Exception as e:
            log.exception("Falha ao calcular rota favorita")
            return jsonify({"erro": str(e)}), 500

    # ══════════════════════════════════════════════════════════
    # Cards do Google (Calendar + Gmail) — frontend chama via chat,
    # mas expostos aqui também pra integrações externas
    # ══════════════════════════════════════════════════════════

    @app.route("/api/agenda", methods=["GET"])
    def api_agenda():
        periodo = request.args.get("periodo", "hoje")
        return jsonify({"dados": listar_eventos_google.invoke({"periodo": periodo})})

    @app.route("/api/emails", methods=["GET"])
    def api_emails():
        termo = request.args.get("termo", "")
        apenas_nao_lidos = request.args.get("nao_lidos", "0") == "1"
        return jsonify({
            "dados": buscar_emails_gmail.invoke({
                "termo": termo, "apenas_nao_lidos": apenas_nao_lidos, "max_resultados": 5
            })
        })

    # ══════════════════════════════════════════════════════════
    # Chat principal (LangGraph com memória por sessão)
    # ══════════════════════════════════════════════════════════

    @app.route("/chat", methods=["POST"])
    def chat():
        dados = request.get_json(silent=True) or {}
        mensagem = str(dados.get("mensagem", "")).strip()[:MAX_MESSAGE_LEN]
        if not mensagem:
            return jsonify({"resposta": "Mensagem vazia."}), 400

        session.setdefault("session_id", str(uuid.uuid4()))
        config = {"configurable": {"thread_id": session["session_id"]}}

        try:
            resultado = agente.invoke(
                {"messages": [HumanMessage(content=mensagem)]},
                config=config,
            )
            resposta = resultado["messages"][-1].content
            resposta = re.sub(r"<think>.*?</think>", "", resposta, flags=re.DOTALL).strip()
            return jsonify({"resposta": resposta})
        except Exception as e:
            log.exception("Falha ao processar mensagem")
            return jsonify({
                "resposta": f"⚠️ Erro ao processar com {OLLAMA_MODEL}: {type(e).__name__}. "
                            f"Verifique se o Ollama está rodando."
            }), 500

    # ══════════════════════════════════════════════════════════
    # Chat com streaming SSE + pré-dispatch de tools
    # ══════════════════════════════════════════════════════════

    @app.route("/chat/stream", methods=["POST"])
    def chat_stream():
        dados = request.get_json(silent=True) or {}
        mensagem = str(dados.get("mensagem", "")).strip()[:MAX_MESSAGE_LEN]
        if not mensagem:
            return jsonify({"erro": "Mensagem vazia."}), 400

        from flask import Response, stream_with_context

        def gerar():
            try:
                llm = ChatOllama(
                    model=OLLAMA_MODEL,
                    temperature=0.3,
                    timeout=120,
                    base_url=OLLAMA_HOST,
                    num_predict=512,
                    num_ctx=4096,
                    extra_body={"think": False},
                )

                msgs = [SystemMessage(content=SYSTEM_PROMPT)]
                tl = mensagem.lower()
                extras = []

                # Pré-dispatch: detecta intenção e chama tool
                if any(w in tl for w in ["notícia", "noticia", "manchete", "jornal", "rio", "brasil", "g1", "globo"]):
                    yield sse_status("Buscando notícias em 17 portais...")
                    extras.append(f"[DADOS DE NOTÍCIAS COLETADOS AGORA]\n{buscar_noticias_rj_brasil.invoke({'tema': 'geral'})}")

                if any(w in tl for w in ["bolsa", "ibovespa", "ação", "petr", "vale", "itub"]):
                    yield sse_status("Cotando Ibovespa + principais ações...")
                    extras.append(f"[DADOS DA B3]\n{buscar_bolsa_valores.invoke({})}")

                if any(w in tl for w in ["clima", "tempo", "chuva", "temperatura"]):
                    yield sse_status("Consultando OpenWeather...")
                    extras.append(f"[CLIMA]\n{clima_rio_janeiro.invoke({'previsao': 'atual'})}")

                if any(w in tl for w in ["flamengo", "flu", "vasco", "botafogo", "brasileirão", "libertadores"]):
                    yield sse_status("Buscando dados esportivos...")
                    extras.append(f"[ESPORTES]\n{estatisticas_esportes.invoke({'esporte': 'brasileirao'})}")

                if any(w in tl for w in ["agenda", "compromisso", "reunião hoje", "reunião amanh"]):
                    yield sse_status("Consultando Google Calendar...")
                    extras.append(f"[AGENDA]\n{listar_eventos_google.invoke({'periodo': 'hoje'})}")

                if any(w in tl for w in ["e-mail", "inbox", "caixa de entrada", "não lidos"]):
                    yield sse_status("Lendo Gmail...")
                    extras.append(f"[INBOX]\n{buscar_emails_gmail.invoke({'apenas_nao_lidos': True, 'max_resultados': 5})}")

                if any(w in tl for w in ["invest", "carteira", "tesouro", "cdb"]):
                    yield sse_status("Analisando investimentos...")
                    extras.append(f"[INVESTIMENTOS]\n{analisar_investimentos.invoke({'perfil': 'moderado'})}")

                if any(w in tl for w in ["rota", "trajeto", "como ir", "ir para"]):
                    yield sse_status("Calculando rota...")
                    extras.append(f"[ROTA]\n{rota_para_destino_favorito.invoke({'nome_destino': 'trabalho', 'modo': 'driving'})}")

                # Monta prompt com dados extras (se houver)
                if extras:
                    prompt_final = mensagem + "\n\n" + "\n\n".join(extras)
                else:
                    prompt_final = mensagem

                msgs.append(HumanMessage(content=prompt_final))

                # Stream da resposta do LLM
                buffer = []
                for chunk in llm.stream(msgs):
                    if hasattr(chunk, "content") and chunk.content:
                        texto = re.sub(r"<think>.*?</think>", "", chunk.content, flags=re.DOTALL)
                        if texto:
                            buffer.append(texto)
                            yield sse_chunk(texto)

                # Fallback se stream veio vazio
                if not buffer:
                    yield sse_chunk("⚠️ O modelo não retornou conteúdo.")
            except Exception as e:
                log.exception("Erro no streaming")
                yield sse_chunk(f"\n\n⚠️ Erro: {type(e).__name__}: {e}")

        return Response(
            stream_with_context(gerar()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


# ── Helpers internos ──────────────────────────────────────────────

def _calc_rota_direta(origem: str, destino: str, modo: str) -> str:
    from tools import calcular_rota
    return calcular_rota.invoke({"origem": origem, "destino": destino, "modo": modo})


def sse_status(msg: str) -> str:
    return f"data: {_json.dumps({'status': msg}, ensure_ascii=False)}\n\n"


def sse_chunk(texto: str) -> str:
    return f"data: {_json.dumps({'chunk': texto}, ensure_ascii=False)}\n\n"