#!/bin/bash

set -e

REPO_DIR="/mnt/c/Users/mnday/Stock_Trading_Pipeline"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$LOG_DIR"

cd "$REPO_DIR/src/agents"

echo "========== $(date) ==========" >> "$LOG_DIR/god_prompt.log"

python3 research_agents.py >> "$LOG_DIR/god_prompt.log" 2>&1

cd "$REPO_DIR"

git add src/agents/ticker_universe.json

git diff --cached --quiet || (
    git commit -m "Monthly God Prompt ticker update"
    git push
)
