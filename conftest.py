"""pytest.ini / conftest.py raiz — garante que `import tools` funcione em CI."""

import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).parent))