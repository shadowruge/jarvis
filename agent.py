"""
agent.py — Construção do agente LangGraph (grafos de estado + memória).

O agente é um StateGraph com 2 nós:
  - "agent" → chama o LLM (ChatOllama) com as mensagens + tools
  - "tools" → ToolNode que executa as tools chamadas pelo LLM

Loop: START → agent → (tem tool_calls? tools : END) → tools → agent → ...

Memória: MemorySaver com thread_id por sessão (mantém contexto entre mensagens).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from functools import lru_cache
from typing import Annotated

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from tools import ALL_TOOLS

log = logging.getLogger(__name__)

# ── Configuração Ollama ──────────────────────────────────────────
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "minimax-m3:cloud")
OLLAMA_HOST  = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

TODAY = date.today().strftime("%d/%m/%Y")
HORA  = datetime.now().strftime("%H:%M")

SYSTEM_PROMPT = f"""Você é o Agente Diário, assistente pessoal do Rio de Janeiro.
Responda SEMPRE em português brasileiro, de forma breve e direta.
Data: {TODAY} {HORA}

Especialidades:
- 🌤️ Clima do Rio (OpenWeather)
- 📰 Notícias do RJ/Brasil (17 portais)
- 📈 Bolsa (Ibovespa, B3)
- ⚽ Esportes (Flamengo, Flu, Vasco, Botafogo, Brasileirão, Libertadores)
- 🗺️ Rotas e trajetos no Rio (carro, a pé, bicicleta)
- 💰 Investimentos (conservador/moderado/arrojado)
- 📧 Classificação de e-mails
- 📅 Google Calendar (listar, buscar, criar eventos)
- ✉️ Gmail (buscar, ler, classificar, enviar)

Use emojis com moderação. Se receber dados de ferramenta, use-os na resposta.

Quando o usuário mencionar:
- "destino", "ir para", "chegar em", "trajeto", "rota", "como ir" → acione a tool de rotas
- "trabalho", "casa", "aeroporto" sem modo específico → ofereça as 3 opções (carro/a pé/bike)
- "notícia", "manchete", "rio", "g1", "globo" → acione busca de notícias
- "bolsa", "ibovespa", "ação", "petr4" → acione dados da bolsa
- "clima", "tempo", "chuva", "temperatura" → acione OpenWeather
- "flamengo", "flu", "vasco", "botafogo", "brasileirão" → acione esportes
- "invest", "carteira", "tesouro", "cdb", "fii" → acione análise de investimentos
- "classifique", "categorize" (e-mail) → acione classificador
- "agenda", "compromisso", "reunião hoje/amanhã/semana" → acione listar_eventos_google
- "criar evento", "agendar", "marcar reunião" → acione criar_evento_google
- "buscar evento", "tem reunião sobre X" → acione buscar_eventos_google
- "e-mail", "inbox", "caixa de entrada", "não lidos" → acione buscar_emails_gmail
- "ler e-mail", "abrir e-mail" → acione ler_email_gmail
- "classificar inbox", "organizar e-mails" → acione classificar_inbox_gmail
- "enviar e-mail", "mandar mensagem pra X" → acione enviar_email_gmail"""


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


@lru_cache(maxsize=1)
def build_agent():
    """Compila o StateGraph do agente (cached — singleton por processo)."""
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        temperature=0.3,
        timeout=600,
        base_url=OLLAMA_HOST,
        num_predict=1024,
        num_ctx=4096,
        repeat_penalty=1.2,
        extra_body={"think": False},   # desliga thinking do qwen3 (acelera MUITO em CPU)
    ).bind_tools(ALL_TOOLS)

    tool_node = ToolNode(ALL_TOOLS)

    def chamar_modelo(state: AgentState):
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=SYSTEM_PROMPT), *msgs]
        resposta = llm.invoke(msgs)
        return {"messages": [resposta]}

    def deve_continuar(state: AgentState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    wf = StateGraph(AgentState)
    wf.add_node("agent", chamar_modelo)
    wf.add_node("tools", tool_node)
    wf.add_edge(START, "agent")
    wf.add_conditional_edges("agent", deve_continuar, {"tools": "tools", END: END})
    wf.add_edge("tools", "agent")
    return wf.compile(checkpointer=MemorySaver())


# Singleton — importado por routes.py
agente = build_agent()