"""tools/google.py — Interface unificada para Calendar + Gmail.

Encapsula o `google_services.py` original em um único tool roteável,
que detecta a intenção (listar/buscar/criar evento, ler/buscar/enviar
e-mail, classificar inbox) via sub-comando.

Princípio:
  Modelos pequenos se perdem com 6-7 tools separadas. Esta tool
  única + `acao` + `parametros` em linguagem natural é mais
  previsível para o LLM rotear.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

import google_services as gs

log = logging.getLogger(__name__)

_ACOES_VALIDAS = (
    "listar_eventos", "buscar_evento", "criar_evento",
    "buscar_emails", "ler_email", "classificar_inbox", "enviar_email",
)


@tool
def gerenciar_agenda_gmail(acao: str, **parametros: str | int | bool) -> str:
    """Gerencia Google Calendar e Gmail em uma única tool.

    Ações disponíveis (escolha UMA e passe os parâmetros relevantes):
      • listar_eventos(periodo='hoje'|'amanha'|'semana'|'proximos7')
      • buscar_evento(termo='reunião cliente X')
      • criar_evento(titulo='Dentista', inicio='2026-06-25T14:00', duracao_minutos=60)
      • buscar_emails(termo='fatura', apenas_nao_lidos=True, max_resultados=5)
      • ler_email(mensagem_id='abc123')
      • classificar_inbox(max_resultados=10)
      • enviar_email(para='fulano@email.com', assunto='Oi', corpo='Texto')

    Se a ação for ambígua ou faltar parâmetro crítico, a tool retorna
    mensagem amigável pedindo mais detalhes.
    """
    a = acao.lower().strip().replace(" ", "_")
    try:
        if a == "listar_eventos":
            return gs.listar_eventos(periodo=str(parametros.get("periodo", "hoje")))

        if a == "buscar_evento":
            termo = str(parametros.get("termo", "")).strip()
            if not termo:
                return "⚠️ Informe o termo de busca (buscar_evento)."
            return gs.buscar_eventos(termo=termo)

        if a == "criar_evento":
            titulo = str(parametros.get("titulo", "")).strip()
            inicio = str(parametros.get("inicio", "")).strip()
            if not titulo or not inicio:
                return "⚠️ criar_evento precisa de 'titulo' e 'inicio'."
            return gs.criar_evento(
                titulo=titulo,
                inicio=inicio,
                duracao_minutos=int(parametros.get("duracao_minutos", 60)),
                descricao=str(parametros.get("descricao", "")),
                local=str(parametros.get("local", "")),
            )

        if a == "buscar_emails":
            return gs.buscar_emails(
                termo=str(parametros.get("termo", "")),
                max_resultados=int(parametros.get("max_resultados", 5)),
                apenas_nao_lidos=bool(parametros.get("apenas_nao_lidos", False)),
            )

        if a == "ler_email":
            mid = str(parametros.get("mensagem_id", "")).strip()
            if not mid:
                return "⚠️ Informe o mensagem_id do e-mail."
            return gs.ler_email(mensagem_id=mid)

        if a == "classificar_inbox":
            return gs.classificar_inbox(max_resultados=int(parametros.get("max_resultados", 10)))

        if a == "enviar_email":
            para = str(parametros.get("para", "")).strip()
            assunto = str(parametros.get("assunto", "")).strip()
            corpo = str(parametros.get("corpo", "")).strip()
            if not (para and assunto and corpo):
                return "⚠️ enviar_email precisa de 'para', 'assunto' e 'corpo'."
            return gs.enviar_email(para=para, assunto=assunto, corpo=corpo)

        return (
            f"⚠️ Ação '{acao}' não reconhecida. "
            f"Use uma de: {', '.join(_ACOES_VALIDAS)}"
        )
    except Exception as e:
        log.exception("Falha no google_services (%s)", a)
        return f"⚠️ Erro ao executar '{acao}': {type(e).__name__}"
