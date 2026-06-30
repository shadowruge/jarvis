"""agent.py — Construção do agente LangGraph (grafo + memória + singleton).

Estado:
  AgentState{ messages: Annotated[list, add_messages] }

Nós:
  - "agent"  → ChatOllama com tools bindadas
  - "tools"  → ToolNode do LangGraph

Arestas:
  START → agent → (tool_calls? tools : END) → tools → agent

Singleton: `agente` é cacheado por processo via lru_cache.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from .config import agent_config
from .tools import ALL_TOOLS

log = logging.getLogger(__name__)


# ── System prompt (template armazenado em arquivo separado) ────────
_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"


def load_system_prompt() -> str:
    """Carrega prompt de arquivo .txt e injeta data/hora atual."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(data_hora=datetime.now().strftime("%d/%m/%Y %H:%M"))


# ── Estado do grafo ──────────────────────────────────────────────
class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]


# ── Construção do grafo (cached) ─────────────────────────────────
@lru_cache(maxsize=1)
def build_agent():
    """Compila o StateGraph. Singleton por processo."""
    cfg = agent_config()
    log.info("Construindo agente: model=%s host=%s", cfg.model, cfg.base_url)

    llm = ChatOllama(
        model=cfg.model,
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        timeout=600,
        num_predict=cfg.num_predict,
        num_ctx=cfg.num_ctx,
        repeat_penalty=cfg.repeat_penalty,
        extra_body={"think": cfg.think_mode},
    ).bind_tools(ALL_TOOLS)

    tool_node = ToolNode(ALL_TOOLS)
    prompt = load_system_prompt()

    def chamar_modelo(state: AgentState) -> dict:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=prompt), *msgs]
        resposta = llm.invoke(msgs)
        return {"messages": [resposta]}

    def deve_continuar(state: AgentState) -> str:
        """Decide se vai pra tools ou finaliza. Edge condicional."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    wf = StateGraph(AgentState)
    wf.add_node("agent", chamar_modelo)
    wf.add_node("tools", tool_node)
    wf.add_edge(START, "agent")
    wf.add_conditional_edges(
        "agent", deve_continuar, {"tools": "tools", END: END}
    )
    wf.add_edge("tools", "agent")

    return wf.compile(checkpointer=MemorySaver())


# Singleton — importado por routes.py
agente = build_agent()
