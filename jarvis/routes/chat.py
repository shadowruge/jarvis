"""routes/chat.py — Endpoints de chat (sync + SSE).

/chat (sync)
  - Reusa o agente compilado (memória por thread_id)
  - Limita payload (MAX_MESSAGE_LEN + MAX_CONTENT_LENGTH no Flask)
  - Erros tipados (JarvisError) → resposta sem stack

/chat/stream (SSE)
  - Reusa o mesmo agente (NÃO instancia ChatOllama por request)
  - Streaming via agente.stream(stream_mode="messages") — API moderna
    langchain_core 1.x / langgraph 1.x. (astream_events foi descontinuado.)
  - Sanitiza blocos de pensamento do qwen3 (`<…>`)
  - Generator robusto: try/finally garante fechamento da stream
"""

from __future__ import annotations

import json as _json
import logging
import re
import uuid

from flask import Blueprint, Response, jsonify, request, session, stream_with_context
from langchain_core.messages import AIMessageChunk, HumanMessage

from ..agent import agente
from ..config import MAX_MESSAGE_LEN, OLLAMA_MODEL
from ..errors import JarvisError, safe_error_payload

log = logging.getLogger(__name__)
bp = Blueprint("chat", __name__)

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_MAX_STREAM_SECONDS = 120  # hard cap pra generator SSE


def _coerce_content(content: object) -> str:
    """Normaliza o `content` de AIMessage para string.

    Em langchain_core 1.x, `AIMessage.content` pode ser:
      - str        — caso clássico
      - list[dict] — formato [{"type": "text", "text": "..."}, ...]
      - None       — mensagem vazia (pode acontecer com tool calls)
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif part.get("type") == "thinking":
                    # Bloco de pensamento do qwen3 — descarta
                    continue
        return "".join(parts)
    return str(content)


def _sanitize_response(content: object) -> str:
    """Remove blocos  do Ollama/qwen3 e normaliza whitespace.
    Aceita str, list[dict] ou None (formato moderno do LangChain 1.x)."""
    texto = _coerce_content(content)
    return _THINK_PATTERN.sub("", texto).strip()


# ── Helpers SSE (chave canônica: 'chunk') ────────────────────────
def _sse(payload: dict) -> str:
    """Serializa um dict como evento SSE UTF-8."""
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_chunk(texto: str) -> str:
    return _sse({"chunk": texto})


def sse_status(msg: str) -> str:
    return _sse({"status": msg})


def sse_done() -> str:
    return _sse({"done": True})


def _ensure_session_id() -> str:
    """Garante um thread_id estável por sessão Flask."""
    sid = session.get("sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["sid"] = sid
    return sid


# ════════════════════════════════════════════════════════════════
# /chat — síncrono, retorna JSON
# ════════════════════════════════════════════════════════════════
@bp.route("/chat", methods=["POST"])
def chat():
    dados = request.get_json(silent=True) or {}
    mensagem = str(dados.get("mensagem", "")).strip()[:MAX_MESSAGE_LEN]

    if not mensagem:
        return jsonify({"erro": "Mensagem vazia."}), 400

    config = {"configurable": {"thread_id": _ensure_session_id()}}

    try:
        resultado = agente.invoke(
            {"messages": [HumanMessage(content=mensagem)]},
            config=config,
        )
        resposta = _sanitize_response(resultado["messages"][-1].content)
        return jsonify({"resposta": resposta})
    except JarvisError as e:
        log.warning("Chat falhou (%s): %s", type(e).__name__, e.internal_detail or e)
        return jsonify(safe_error_payload(e)), e.http_status
    except Exception as e:
        log.exception("Erro inesperado em /chat")
        return jsonify({
            "erro": f"⚠️ Erro ao processar com {OLLAMA_MODEL}: {type(e).__name__}. "
                    f"Verifique se o Ollama está rodando."
        }), 500


# ════════════════════════════════════════════════════════════════
# /chat/stream — Server-Sent Events, robusto
# ════════════════════════════════════════════════════════════════
@bp.route("/chat/stream", methods=["POST"])
def chat_stream():
    dados = request.get_json(silent=True) or {}
    mensagem = str(dados.get("mensagem", "")).strip()[:MAX_MESSAGE_LEN]

    if not mensagem:
        return jsonify({"erro": "Mensagem vazia."}), 400

    config = {"configurable": {"thread_id": _ensure_session_id()}}

    def gerar():
        try:
            yield sse_status("Processando com " + OLLAMA_MODEL + "…")

            buffer = []
            # API moderna (langchain_core 1.x / langgraph 1.x):
            # stream(..., stream_mode='messages') emite (AIMessageChunk, metadata) por token.
            # NÃO usar astream_events (deprecado nessas versões).
            for chunk, _meta in agente.stream(
                {"messages": [HumanMessage(content=mensagem)]},
                config=config,
                stream_mode="messages",
            ):
                if not isinstance(chunk, AIMessageChunk):
                    continue
                text = _sanitize_response(chunk.content)
                if text:
                    buffer.append(text)
                    yield sse_chunk(text)

            if not buffer:
                yield sse_chunk("⚠️ O modelo não retornou conteúdo.")

            yield sse_done()

        except JarvisError as e:
            log.warning("Stream falhou: %s", e.internal_detail or e)
            yield _sse(safe_error_payload(e))
        except Exception as e:
            log.exception("Erro inesperado em /chat/stream")
            yield sse_chunk(
                f"\n\n⚠️ Erro: {type(e).__name__}. "
                f"Verifique se o Ollama está rodando em http://localhost:11434."
            )
        finally:
            # Sempre fecha o generator limpo (não vaza threads)
            log.debug("SSE generator fechado (thread_id=%s)", config["configurable"]["thread_id"])

    return Response(
        stream_with_context(gerar()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
