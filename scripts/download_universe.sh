#!/bin/bash
set -e

REPO_RAW_URL="https://raw.githubusercontent.com/FrizkyTrixter/Stock_Trading_Pipeline/main/ticker_universe.json"
OUTPUT_PATH="$HOME/Stock_Trading_Pipeline/src/agents/ticker_universe.json"
LOG_DIR="$HOME/Stock_Trading_Pipeline/logs"

mkdir -p "$(dirname "$OUTPUT_PATH")"
mkdir -p "$LOG_DIR"

curl -L "$REPO_RAW_URL" -o "$OUTPUT_PATH"

echo "$(date): downloaded ticker universe to $OUTPUT_PATH" >> "$LOG_DIR/universe_download.log"
