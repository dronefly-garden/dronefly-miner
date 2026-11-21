#!/bin/bash
set -euo pipefail

: "${HOME:?HOME is not set}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA_DIR="$XDG_DATA_HOME/dronefly-miner"
REPO_DIR="${DRONEFLY_MONOREPO:-$HOME/dronefly-monorepo}"
MASTER_DB="$DATA_DIR/taxa.db"
LOG_FILE="$DATA_DIR/build.log"

if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
else
    UV_BIN="$HOME/.local/bin/uv"
fi

mkdir -p "$DATA_DIR"

{
    cd "$REPO_DIR"
    "$UV_BIN" run --package dronefly-miner dronefly-miner build

    shopt -s nullglob
    for target_db in "$DATA_DIR"/taxa-*.db; do
        case "$(basename "$target_db")" in
            *.tmp*) continue ;;
        esac
        tmp_db="${target_db}.tmp.$$"
        python3 -c '
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
' "$MASTER_DB" "$tmp_db"
        mv -f "$tmp_db" "$target_db"
        echo "Synced $(basename "$target_db") from $(basename "$MASTER_DB")"
    done
} > "$LOG_FILE" 2>&1
