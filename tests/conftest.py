"""conftest.py — Configuração compartilhada dos testes pytest.

Garante que Ollama não é chamado em CI (não está rodando lá) e que
eventuais credenciais do Google não sejam necessárias.
"""

import os
import sys
from pathlib import Path

# Garante raiz do projeto no sys.path (necessário para achar `jarvis/`)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Variáveis dummy só pra evitar KeyError nos imports.
os.environ.setdefault("OLLAMA_MODEL", "fake-model")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-only-for-tests-not-prod")
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ.setdefault("FAVORITE_DESTINATIONS", "")