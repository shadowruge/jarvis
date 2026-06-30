"""tools/rotas.py — Rotas no Rio de Janeiro.

Consolida `calcular_rota` + `rota_para_destino_favorito` num único
tool com detecção de intent. Usa Mapbox se houver chave, senão OSRM.

Geocode: Nominatim (OSM) — gratuito e respeitoso (com User-Agent).
"""

from __future__ import annotations

import logging
from typing import Final

from langchain_core.tools import tool

from ..config import (
    DEFAULT_HOME,
    FAVORITE_DESTINATIONS,
    MAPBOX_API_KEY,
    RJ_BAIRROS,
)
from ..http_client import get_json

log = logging.getLogger(__name__)

_MODO_LABELS: Final[dict[str, str]] = {
    "driving": "🚗 Carro",
    "walking": "🚶 A pé",
    "cycling": "🚴 Bicicleta",
}

_FAVORITOS_NORM: Final[frozenset[str]] = frozenset({"trabalho", "casa", "aeroporto"})


def _parse_favoritos() -> dict[str, str]:
    """Parseia FAVORITE_DESTINATIONS do .env em dict {nome_lower: endereço}."""
    if not FAVORITE_DESTINATIONS:
        return {}
    out: dict[str, str] = {}
    for item in FAVORITE_DESTINATIONS.split(";"):
        item = item.strip()
        if "|" not in item:
            continue
        nome, end = item.split("|", 1)
        out[nome.strip().lower()] = end.strip()
    return out


_FAVORITOS: dict[str, str] = _parse_favoritos()


def _geocode(endereco: str) -> tuple[float, float] | None:
    """Geocodifica endereço → (lat, lon). Nominatim primeiro (sem custo)."""
    addr_norm = endereco.lower().strip()
    busca = RJ_BAIRROS.get(addr_norm, endereco)
    try:
        data = get_json(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": busca, "format": "json", "limit": 1, "countrycodes": "br",
            },
            timeout=8.0,
        )
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        log.debug("geocode falhou: %s", e)

    if MAPBOX_API_KEY:
        try:
            data = get_json(
                f"https://api.mapbox.com/geocoding/v5/mapbox.places/"
                f"{busca.replace(' ', '%20')}.json",
                params={"access_token": MAPBOX_API_KEY, "limit": 1},
            )
            feats = data.get("features", [])
            if feats:
                lon, lat = feats[0]["center"]
                return float(lat), float(lon)
        except Exception as e:
            log.debug("mapbox geocode falhou: %s", e)
    return None


def _is_coord(s: str) -> bool:
    try:
        parts = [p.strip() for p in s.split(",")]
        return len(parts) == 2 and all(float(p) for p in parts) is not None  # noqa: PLR0124
    except (ValueError, TypeError):
        return False


def _parse_coord(s: str) -> tuple[float, float] | None:
    try:
        parts = [p.strip() for p in s.split(",")]
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


def _resolve_coord(endereco: str) -> tuple[float, float] | None:
    if _is_coord(endereco):
        return _parse_coord(endereco)
    return _geocode(endereco)


def _format_rota(origem: str, destino: str, modo: str,
                 distancia_km: float, duracao_min: float,
                 instrucoes: list[str], provedor: str) -> str:
    label = _MODO_LABELS.get(modo, modo)
    head = f"🗺️ **Rota — {label}**" + (f" ({provedor})" if provedor else "")
    steps = "\n".join(f"  • {i}" for i in instrucoes if i) or "  • (sem instruções)"
    return (
        f"{head}\n"
        f"📍 De: {origem}\n🏁 Até: {destino}\n\n"
        f"📏 Distância: **{distancia_km:.1f} km**\n"
        f"⏱️ Tempo estimado: **{duracao_min:.0f} min**\n\n"
        f"📋 Primeiros passos:\n{steps}"
    )


def _via_mapbox(origem: str, destino: str, modo: str) -> tuple[float, float, float, list[str]] | None:
    """Tenta via Mapbox Directions. Retorna (km, min, instrucoes) ou None."""
    coord_o = _resolve_coord(origem)
    coord_d = _resolve_coord(destino)
    if not (coord_o and coord_d):
        return None

    lat1, lon1 = coord_o
    lat2, lon2 = coord_d
    profile = {"driving": "driving", "walking": "foot", "cycling": "cycling"}.get(modo, "driving")

    try:
        data = get_json(
            f"https://api.mapbox.com/directions/v5/mapbox/{profile}/"
            f"{lon1},{lat1};{lon2},{lat2}",
            params={"steps": "true", "overview": "simplified", "geometries": "geojson"},
        )
        if not data.get("routes"):
            return None
        rota = data["routes"][0]
        km = rota["distance"] / 1000
        mins = rota["duration"] / 60
        steps = rota.get("legs", [{}])[0].get("steps", [])
        instr = [s.get("maneuver", {}).get("instruction", "") for s in steps[:6]]
        return km, mins, [i for i in instr if i]
    except Exception as e:
        log.debug("mapbox directions falhou: %s", e)
        return None


def _via_osrm(origem: str, destino: str, modo: str) -> tuple[float, float, float, list[str]] | None:
    """Fallback via OSRM público (sem chave)."""
    coord_o = _resolve_coord(origem)
    coord_d = _resolve_coord(destino)
    if not (coord_o and coord_d):
        return None

    lat1, lon1 = coord_o
    lat2, lon2 = coord_d
    profile = {"driving": "driving", "walking": "foot", "cycling": "bike"}.get(modo, "driving")

    try:
        data = get_json(
            f"http://router.project-osrm.org/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}",
            params={"steps": "true", "overview": "false"},
        )
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        rota = data["routes"][0]
        km = rota["distance"] / 1000
        mins = rota["duration"] / 60
        steps = rota.get("legs", [{}])[0].get("steps", [])
        instr = []
        for s in steps[:6]:
            m = s.get("maneuver", {}).get("instruction") or (
                f"{s.get('name', '(rua)')} ({s.get('distance', 0):.0f}m)"
            )
            instr.append(m)
        return km, mins, instr
    except Exception as e:
        log.debug("osrm falhou: %s", e)
        return None


@tool
def calcular_rota_rio(
    origem: str = "",
    destino: str = "",
    modo: str = "driving",
    nome_destino: str = "",
) -> str:
    """Calcula rota no Rio de Janeiro.

    Args:
        origem:      endereço (bairro/rua) ou coordenadas "lat,lon". Default: sua casa.
        destino:     endereço completo. Ignorado se nome_destino for um favorito.
        modo:        'driving' (carro) | 'walking' (a pé) | 'cycling' (bike).
        nome_destino: apelido do favorito em FAVORITE_DESTINATIONS (.env).
                      'trabalho' | 'casa' | 'aeroporto' | nome custom.

    Usa Mapbox se MAPBOX_API_KEY estiver definida; senão OSRM público.
    """
    modo_norm = modo.lower().strip()
    if modo_norm not in _MODO_LABELS:
        return f"⚠️ Modo '{modo}' inválido. Use: driving | walking | cycling"

    # resolve favorito
    if nome_destino and nome_destino.lower().strip() in _FAVORITOS_NORM:
        end = _FAVORITOS.get(nome_destino.lower().strip())
        if not end:
            lista = ", ".join(_FAVORITOS.keys()) or "(nenhum configurado)"
            return f"⚠️ Favorito '{nome_destino}' não configurado. Disponíveis: {lista}"
        origem = origem or DEFAULT_HOME
        destino = end

    if not origem or not destino:
        return "⚠️ Informe origem E destino (ou um nome_destino favorito válido)."

    # Mapbox primeiro
    if MAPBOX_API_KEY:
        res = _via_mapbox(origem, destino, modo_norm)
        if res:
            km, mins, instr = res
            return _format_rota(origem, destino, modo_norm, km, mins, instr, "Mapbox")

    # OSRM fallback
    res = _via_osrm(origem, destino, modo_norm)
    if res:
        km, mins, instr = res
        return _format_rota(origem, destino, modo_norm, km, mins, instr, "OSRM público")

    return f"⚠️ Não consegui calcular rota para {origem} → {destino}"
