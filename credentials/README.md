# Credentials — Pasta local apenas

Esta pasta **NUNCA** deve ir pro git. Ela guarda:

- `google_credentials.json` — OAuth client (vem do Google Cloud Console)
- `google_token.json` — token do usuário (gerado automaticamente na primeira auth)

## Como configurar (passo a passo)

### 1. Criar projeto no Google Cloud

1. Acesse https://console.cloud.google.com
2. Crie um projeto novo (ex: "jarvis-agente")
3. Ative as APIs:
   - **Google Calendar API**
   - **Gmail API**

### 2. Criar credenciais OAuth

1. Menu lateral → **APIs e serviços** → **Credenciais**
2. **Criar credenciais** → **ID do cliente OAuth**
3. Tipo de aplicativo: **Aplicativo para computador (Desktop)**
4. Nome: `jarvis-desktop`
5. Em **URI de redirecionamento autorizado**, deixe como está (o fluxo `run_local_server` cuida)
6. Baixe o JSON e salve aqui como `google_credentials.json`

### 3. Configurar tela de consentimento

1. **APIs e serviços** → **Tela de consentimento OAuth**
2. User type: **Externo** (se não tiver organização Google Workspace)
3. Preencha o básico (nome do app, e-mail de suporte)
4. Em **Escopos**, adicione:
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send` (opcional, pra enviar)
5. Em **Usuários de teste**, adicione o seu e-mail Gmail

### 4. Primeira execução

```bash
python main.py
```

Quando você usar qualquer tool do Google pela primeira vez, o navegador abre pedindo autorização. Depois o token é salvo em `google_token.json` e reutilizado silenciosamente.

---

## ⚠️ Segurança

- Nunca commite `google_credentials.json` nem `google_token.json`
- Se você acidentalmente expôs o JSON, revogue a credencial no Google Cloud Console e gere outra
- O token dá acesso à sua agenda e e-mails — trate como senha