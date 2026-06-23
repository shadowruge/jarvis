# 🤖 Agente Diário — RJ

Assistente pessoal com IA local (Ollama + qwen3:0.6b) para o seu dia a dia no Rio de Janeiro.

## ✨ Funcionalidades

| Módulo | Descrição |
|---|---|
| 📧 **E-mails** | Cole qualquer e-mail e o agente classifica (urgente, financeiro, spam, trabalho, pessoal) |
| 📰 **Notícias** | Resumo das principais notícias do RJ e do Brasil (via RSS G1, O Globo) |
| 📈 **Bolsa** | Ibovespa + ações principais (PETR4, VALE3, ITUB4, WEGE3...) em tempo real |
| 💰 **Investimentos** | Análise e carteira sugerida por perfil: conservador, moderado ou arrojado |

---

## 🚀 Como rodar

### 1. Instale o Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Baixe o modelo
```bash
ollama pull qwen3:0.6b
```

### 3. Instale as dependências Python
```bash
pip install -r requirements.txt
```

### 4. Rode o agente
```bash
python main.py
```

### 5. Acesse no navegador
```
http://localhost:5000
```

---

## ⚙️ Variáveis de ambiente (opcionais)

| Variável | Padrão | Descrição |
|---|---|---|
| `OLLAMA_MODEL` | `minimax-m3:cloud` | Modelo Ollama a usar |
| `OLLAMA_HOST` | `http://localhost:11434` | Host do Ollama |
| `FLASK_DEBUG` | `0` | Modo debug (`1` para ativar) |
| `OPENWEATHER_API_KEY` | _(vazio)_ | Chave OpenWeather (grátis em [openweathermap.org](https://openweathermap.org/api)) |
| `MAPBOX_API_KEY` | _(vazio)_ | Chave Mapbox pra rotas (sem ela, usa OSRM público) |
| `FOOTBALL_API_KEY` | _(vazio)_ | API-Football pra dados completos de esportes |

Exemplo:
```bash
OLLAMA_MODEL=qwen3:0.6b FLASK_DEBUG=1 python main.py
```

---

## 📅 Google Calendar + ✉️ Gmail (opcional)

Você pode conectar o jarvis à sua agenda e e-mail pessoais. **Setup único** (sem renovação):

1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com)
2. Ative **Google Calendar API** e **Gmail API**
3. Crie credenciais OAuth do tipo **Aplicativo para desktop**
4. Baixe o JSON e salve em `credentials/google_credentials.json`
5. Rode o jarvis e use qualquer tool do Google — o navegador abre pedindo autorização na primeira vez
6. O token fica salvo em `credentials/google_token.json` (reutilizado depois)

**Detalhes completos em [`credentials/README.md`](credentials/README.md)**

### Tools adicionadas
- `listar_eventos_google("hoje" | "amanha" | "semana" | "proximos7")`
- `buscar_eventos_google("reunião cliente X")`
- `criar_evento_google("Dentista", "2026-06-25T14:00", duracao_minutos=60)`
- `buscar_emails_gmail("fatura", apenas_nao_lidos=True)`
- `ler_email_gmail(mensagem_id)`
- `classificar_inbox_gmail()` — usa o classificador do jarvis nos últimos 10 e-mails
- `enviar_email_gmail("fulano@email.com", "Assunto", "Corpo")`

### Segurança
- `credentials/` está no `.gitignore` — nada vaza pro repo
- Tokens são refreshados automaticamente (não expira)
- Pra revogar: delete `credentials/google_token.json`

---

## 💬 Exemplos de uso

- *"Quais são as notícias de hoje no Rio?"*
- *"Como está o Ibovespa hoje?"*
- *"Invisto R$500/mês, qual a melhor estratégia para perfil conservador?"*
- *"Classifique este e-mail: [cole o e-mail aqui]"*
- *"O que tenho na agenda hoje?"* (requer Google Calendar configurado)
- *"Buscar e-mails não lidos com 'fatura'"* (requer Gmail configurado)
- *"Criar evento dentista sexta 14h por 1 hora"*
- *"Vale mais a pena CDB ou Tesouro Direto agora?"*
- *"O que é um FII e como funciona?"*

---

## 🏗️ Arquitetura

```
Flask (web server)
  └── LangGraph (grafo de estados com memória)
        ├── ChatOllama (qwen3:0.6b local)
        └── Tools:
              ├── buscar_noticias_rj_brasil()  — RSS feeds
              ├── buscar_bolsa_valores()        — Yahoo Finance API
              ├── classificar_email()           — classificação local
              └── analisar_investimentos()      — análise por perfil
```

---

Feito com ❤️ para o Rio de Janeiro 🌊
