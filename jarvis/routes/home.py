"""routes/home.py — Healthcheck e página inicial."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from ..config import OLLAMA_HOST, OLLAMA_MODEL

bp = Blueprint("home", __name__)


@bp.route("/")
def home():
    return render_template("index.html", ollama_model=OLLAMA_MODEL)


@bp.route("/api/info")
def api_info():
    return jsonify({"modelo": OLLAMA_MODEL, "host": OLLAMA_HOST})
