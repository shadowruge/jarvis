"""conftest.py — Configuração compartilhada dos testes pytest.

Garante que Ollama não é chamado em CI (não está rodando lá) e que
eventuais credenciais do Google não sejam necessárias.
"""

import os

# Variáveis dummy só pra evitar KeyError nos imports.
os.environ.setdefault("OLLAMA_MODEL", "fake-model")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-only-for-tests")
os.environ.setdefault("FLASK_DEBUG", "0")