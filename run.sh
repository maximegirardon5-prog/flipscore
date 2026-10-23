#!/usr/bin/env bash
# Script de lancement de FlipScore.
#
#   ./run.sh setup     installe tout (à faire une fois)
#   ./run.sh test      lance les tests
#   ./run.sh dev       démarre l'application sur http://localhost:8000
#   ./run.sh initdb    crée / met à jour les tables de la base
#   ./run.sh job NOM   lance une tâche, ex. : ./run.sh job heartbeat
#   ./run.sh check     vérifie la qualité du code (lint)

set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"

ensure_env() {
  if [ ! -x "$PY" ]; then
    echo "❌ Environnement non installé. Lance d'abord : ./run.sh setup"
    exit 1
  fi
}

case "${1:-help}" in
  setup)
    echo "▶ Création de l'environnement Python…"
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements-dev.txt
    if [ ! -f .env ]; then
      cp .env.example .env
      echo "▶ Fichier .env créé à partir de .env.example (à compléter plus tard)."
    fi
    "$PY" -m app.jobs.init_db
    echo "✅ Installation terminée. Essaie : ./run.sh test"
    ;;
  test)
    ensure_env
    "$PY" -m pytest "${@:2}"
    ;;
  dev)
    ensure_env
    "$PY" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ;;
  initdb)
    ensure_env
    "$PY" -m app.jobs.init_db
    ;;
  job)
    ensure_env
    [ -n "${2:-}" ] || { echo "Usage : ./run.sh job NOM (ex. heartbeat)"; exit 1; }
    "$PY" -m "app.jobs.$2"
    ;;
  check)
    ensure_env
    .venv/bin/ruff check .
    ;;
  *)
    sed -n '2,10p' "$0"
    ;;
esac
