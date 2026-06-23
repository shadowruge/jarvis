"""
google_services.py — Integração com Google Calendar + Gmail via OAuth 2.0 Desktop.

Fluxo de autenticação:
  1. Você cria um projeto no Google Cloud Console (https://console.cloud.google.com)
  2. Ativa as APIs: Google Calendar API + Gmail API
  3. Cria credenciais OAuth do tipo "Aplicativo para computador (Desktop)"
  4. Baixa o JSON e salva em credentials/google_credentials.json
  5. Na primeira execução, abre o navegador pra você autorizar
  6. O token é salvo em credentials/google_token.json (reutilizado depois)

Scopes usados:
  - https://www.googleapis.com/auth/calendar.events   (ler + escrever eventos)
  - https://www.googleapis.com/auth/gmail.readonly     (ler e-mails)
  - https://www.googleapis.com/auth/gmail.send        (enviar e-mails — opcional)
"""

from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────
CREDENTIALS_DIR      = Path(os.getenv("GOOGLE_CREDENTIALS_DIR", "credentials"))
CREDENTIALS_FILE     = CREDENTIALS_DIR / "google_credentials.json"
TOKEN_FILE           = CREDENTIALS_DIR / "google_token.json"

# Scopes solicitados. Se você já tinha token salvo com scopes diferentes,
# apague credentials/google_token.json pra forçar nova autorização.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

# ─── Auth lazy (só autentica quando uma função é chamada) ────────
_services_cache: dict[str, object] = {}


def _build_credentials():
    """Faz o fluxo OAuth e retorna Credentials válidas."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"❌ Credenciais não encontradas em {CREDENTIALS_FILE}.\n"
            "Siga o setup em README.md → seção 'Google Calendar + Gmail'."
        )

    creds: Optional[Credentials] = None

    # Token salvo (reutiliza se ainda válido)
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            log.warning(f"Token inválido, vou refazer auth: {e}")
            creds = None

    # Refresh automático se expirou
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
            log.info("🔄 Token do Google refrescado automaticamente")
        except Exception as e:
            log.warning(f"Falha no refresh: {e}. Vou pedir nova autorização.")
            creds = None

    # Fluxo novo (abre navegador)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        # run_local_server abre o browser e captura o callback
        creds = flow.run_local_server(port=0, open_browser=True)
        TOKEN_FILE.write_text(creds.to_json())
        log.info(f"✅ Token salvo em {TOKEN_FILE}")

    return creds


def _calendar_service():
    if "calendar" not in _services_cache:
        from googleapiclient.discovery import build
        creds = _build_credentials()
        _services_cache["calendar"] = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _services_cache["calendar"]


def _gmail_service():
    if "gmail" not in _services_cache:
        from googleapiclient.discovery import build
        creds = _build_credentials()
        _services_cache["gmail"] = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return _services_cache["gmail"]


def _check_setup() -> Optional[str]:
    """Retorna mensagem de erro se o setup não estiver pronto, senão None."""
    if not CREDENTIALS_FILE.exists():
        return (
            "⚠️ Google não configurado.\n"
            f"Esperado: {CREDENTIALS_FILE}\n"
            "Veja README.md → seção 'Google Calendar + Gmail'."
        )
    return None


# ─── Helpers ─────────────────────────────────────────────────────
def _iso_para_datetime(iso: str) -> datetime:
    """Converte ISO 8601 do Google pra datetime naive em horário local."""
    s = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.astimezone().replace(tzinfo=None)


def _formatar_evento(ev: dict) -> str:
    """Formata um evento do Calendar pra texto legível."""
    titulo = ev.get("summary", "(sem título)")
    inicio = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
    fim    = ev.get("end",   {}).get("dateTime") or ev.get("end",   {}).get("date")
    local  = ev.get("location", "")
    desc   = ev.get("description", "")

    try:
        if "T" in (inicio or ""):
            di = _iso_para_datetime(inicio).strftime("%d/%m %H:%M")
            df = _iso_para_datetime(fim).strftime("%H:%M") if fim else ""
            quando = f"{di}–{df}" if df else di
        else:
            quando = f"📅 dia {datetime.fromisoformat(inicio).strftime('%d/%m/%Y')}"
    except Exception:
        quando = inicio or "?"

    linha = f"• {titulo}  ({quando})"
    if local:
        linha += f"\n   📍 {local}"
    if desc:
        snippet = desc.strip().splitlines()[0][:120]
        linha += f"\n   📝 {snippet}"
    return linha


def _header_bold(b: bytes) -> str:
    """Decodifica header do Gmail (base64url)."""
    try:
        return base64.urlsafe_b64decode(b + b"=" * (-len(b) % 4)).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _formatar_email(msg: dict) -> str:
    """Formata um message do Gmail pra texto legível."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    remetente = headers.get("from", "?")
    assunto   = headers.get("subject", "(sem assunto)")
    data_hdr  = headers.get("date", "")
    snippet   = msg.get("snippet", "")[:140]

    # Data em formato legível
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(data_hdr)
        quando = dt.strftime("%d/%m %H:%M")
    except Exception:
        quando = data_hdr

    # Extrai só o nome do remetente
    nome = re.split(r"<", remetente)[0].strip().strip('"') or remetente
    return f"• {nome} — {assunto}\n   🕐 {quando}\n   💬 {snippet}…"


# ════════════════════════════════════════════════════════════════
# CALENDAR
# ════════════════════════════════════════════════════════════════

def listar_eventos(periodo: str = "hoje", max_resultados: int = 10) -> str:
    """
    Lista eventos do Google Calendar.
    periodo: hoje | amanha | semana | proximos7
    """
    if (err := _check_setup()):
        return err

    tz = timezone.utc  # Calendar API retorna em UTC; convertemos na exibição
    agora = datetime.now(tz)

    if periodo == "hoje":
        ini = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        fim = ini + timedelta(days=1)
        titulo = "📅 Agenda de hoje"
    elif periodo == "amanha":
        ini = (agora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        fim = ini + timedelta(days=1)
        titulo = "📅 Agenda de amanhã"
    elif periodo == "semana":
        # Da segunda-feira desta semana até domingo
        ini = (agora - timedelta(days=agora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        fim = ini + timedelta(days=7)
        titulo = "📅 Agenda da semana"
    elif periodo == "proximos7":
        ini = agora
        fim = agora + timedelta(days=7)
        titulo = "📅 Próximos 7 dias"
    else:
        return f"⚠️ Período inválido: {periodo}. Use: hoje | amanha | semana | proximos7"

    try:
        svc = _calendar_service()
        resp = svc.events().list(
            calendarId="primary",
            timeMin=ini.isoformat(),
            timeMax=fim.isoformat(),
            maxResults=max_resultados,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        eventos = resp.get("items", [])
        if not eventos:
            return f"{titulo}\n\n🎉 Nada agendado."

        linhas = [_formatar_evento(e) for e in eventos]
        return f"{titulo} ({len(eventos)} evento(s)):\n\n" + "\n\n".join(linhas)
    except Exception as e:
        log.exception("Erro ao listar eventos")
        return f"⚠️ Erro no Calendar: {e}"


def buscar_eventos(termo: str, max_resultados: int = 5) -> str:
    """Busca eventos por palavra-chave (no título, descrição ou local)."""
    if (err := _check_setup()):
        return err
    if not termo.strip():
        return "⚠️ termo de busca vazio"

    try:
        svc = _calendar_service()
        agora = datetime.now(timezone.utc)
        resp = svc.events().list(
            calendarId="primary",
            q=termo,
            timeMin=agora.isoformat(),
            maxResults=max_resultados,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        eventos = resp.get("items", [])
        if not eventos:
            return f"🔍 Nenhum evento encontrado pra: '{termo}'"

        linhas = [_formatar_evento(e) for e in eventos]
        return f"🔍 {len(eventos)} resultado(s) pra '{termo}':\n\n" + "\n\n".join(linhas)
    except Exception as e:
        return f"⚠️ Erro na busca: {e}"


def criar_evento(
    titulo: str,
    inicio: str,
    duracao_minutos: int = 60,
    descricao: str = "",
    local: str = "",
    dia_inteiro: bool = False,
) -> str:
    """
    Cria um evento no Google Calendar.
    inicio: ISO 8601 ('2026-06-23T15:00') OU dia inteiro ('2026-06-23') se dia_inteiro=True
    Retorna link do evento criado.
    """
    if (err := _check_setup()):
        return err
    if not titulo.strip():
        return "⚠️ título vazio"

    try:
        body: dict = {"summary": titulo.strip()}
        if descricao:
            body["description"] = descricao
        if local:
            body["location"] = local

        if dia_inteiro:
            body["start"] = {"date": inicio[:10]}
            body["end"]   = {"date": inicio[:10]}
        else:
            # Aceita 'YYYY-MM-DDTHH:MM' ou ISO completo
            ini_dt = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
            if ini_dt.tzinfo is None:
                ini_dt = ini_dt.replace(tzinfo=timezone.utc)  # default UTC se vier naive
            fim_dt = ini_dt + timedelta(minutes=duracao_minutos)
            body["start"] = {"dateTime": ini_dt.isoformat()}
            body["end"]   = {"dateTime": fim_dt.isoformat()}

        svc = _calendar_service()
        ev = svc.events().insert(calendarId="primary", body=body).execute()
        link = ev.get("htmlLink", "")
        return f"✅ Evento criado: {titulo}\n🔗 {link}"
    except ValueError as e:
        return f"⚠️ Data inválida '{inicio}'. Use formato ISO: 2026-06-23T15:00"
    except Exception as e:
        log.exception("Erro ao criar evento")
        return f"⚠️ Erro ao criar evento: {e}"


# ════════════════════════════════════════════════════════════════
# GMAIL
# ════════════════════════════════════════════════════════════════

def buscar_emails(
    termo: str = "",
    max_resultados: int = 5,
    apenas_nao_lidos: bool = False,
    label: str = "INBOX",
) -> str:
    """
    Lista e-mails do Gmail.
    termo: palavra-chave (busca em assunto, corpo, remetente)
    label: INBOX (padrão), SENT, IMPORTANT, STARRED ou label custom (ex: 'Trabalho')
    """
    if (err := _check_setup()):
        return err

    try:
        svc = _gmail_service()
        query = ""
        if termo:
            query = termo
        if apenas_nao_lidos:
            query = (query + " is:unread").strip()
        if label:
            query = (query + f" label:{label}").strip()

        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=max_resultados
        ).execute()

        ids = [m["id"] for m in resp.get("messages", [])]
        if not ids:
            return f"📭 Nenhum e-mail {'não lido ' if apenas_nao_lidos else ''}encontrado"
        if termo:
            titulo = f"📧 {len(ids)} e-mail(s) com '{termo}'"
        elif apenas_nao_lidos:
            titulo = f"📬 {len(ids)} e-mail(s) não lido(s)"
        else:
            titulo = f"📧 {label}: {len(ids)} e-mail(s)"

        # Busca os detalhes em paralelo (request batch seria ideal, mas sequencial basta pra poucos)
        detalhes = []
        for mid in ids:
            msg = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                              metadataHeaders=["From", "Subject", "Date"]).execute()
            detalhes.append(_formatar_email(msg))

        return titulo + "\n\n" + "\n\n".join(detalhes)
    except Exception as e:
        log.exception("Erro ao buscar e-mails")
        return f"⚠️ Erro no Gmail: {e}"


def ler_email(mensagem_id: str) -> str:
    """Lê o conteúdo completo de um e-mail pelo ID (listado pela ferramenta de busca)."""
    if (err := _check_setup()):
        return err
    if not mensagem_id:
        return "⚠️ mensagem_id vazio"

    try:
        svc = _gmail_service()
        msg = svc.users().messages().get(userId="me", id=mensagem_id, format="full").execute()

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        remetente = headers.get("from", "?")
        para      = headers.get("to", "?")
        assunto   = headers.get("subject", "(sem assunto)")
        data_hdr  = headers.get("date", "")

        # Decodifica corpo
        corpo = _extrair_corpo(msg.get("payload", {}))
        if not corpo:
            corpo = msg.get("snippet", "(sem conteúdo)")

        # Limita tamanho
        if len(corpo) > 2500:
            corpo = corpo[:2500] + "\n\n[…corteu em 2500 caracteres…]"

        return (
            f"📧 **{assunto}**\n\n"
            f"👤 De: {remetente}\n"
            f"➡️ Para: {para}\n"
            f"🕐 {data_hdr}\n\n"
            f"---\n{corpo}"
        )
    except Exception as e:
        return f"⚠️ Erro ao ler e-mail: {e}"


def _extrair_corpo(payload: dict) -> str:
    """Extrai texto/plain de um payload do Gmail (recursivo pra partes aninhadas)."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(
            payload["body"]["data"] + "=" * (-len(payload["body"]["data"]) % 4)
        ).decode("utf-8", errors="replace")

    for parte in payload.get("parts", []):
        texto = _extrair_corpo(parte)
        if texto:
            return texto
    return ""


def classificar_inbox(max_resultados: int = 10) -> str:
    """Lê os últimos e-mails da INBOX e aplica a classificação do jarvis."""
    if (err := _check_setup()):
        return err

    # Reaproveita o classificador atual do main.py
    try:
        from main import classificar_email  # type: ignore
    except ImportError:
        return "⚠️ classificador não disponível (main.py não carregado)"

    try:
        svc = _gmail_service()
        resp = svc.users().messages().list(userId="me", q="label:INBOX", maxResults=max_resultados).execute()
        ids = [m["id"] for m in resp.get("messages", [])]
        if not ids:
            return "📭 INBOX vazia"

        resultados = []
        for mid in ids:
            msg = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                              metadataHeaders=["From", "Subject"]).execute()
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            snippet = msg.get("snippet", "")
            texto = f"{headers.get('subject','')}\n{headers.get('from','')}\n{snippet}"
            cat = classificar_email.invoke({"conteudo_email": texto})
            resultados.append(f"• {headers.get('subject','(sem assunto)')[:60]}\n  {cat}")

        return "📬 Classificação da INBOX:\n\n" + "\n\n".join(resultados)
    except Exception as e:
        return f"⚠️ Erro ao classificar: {e}"


def enviar_email(para: str, assunto: str, corpo: str) -> str:
    """Envia um e-mail via Gmail (requer scope gmail.send)."""
    if (err := _check_setup()):
        return err

    # Validação simples
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", para):
        return f"⚠️ Endereço inválido: {para}"

    try:
        svc = _gmail_service()
        mime = MIMEText(corpo, "plain", "utf-8")
        mime["to"]      = para
        mime["subject"] = assunto
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")

        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"✅ E-mail enviado pra {para}\n📨 ID: {sent.get('id')}"
    except Exception as e:
        return f"⚠️ Erro ao enviar: {e}"