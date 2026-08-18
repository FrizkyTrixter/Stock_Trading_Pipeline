#!/bin/bash
set -e

PROJECT_DIR="/mnt/c/Users/mnday/Stock_Trading_Pipeline"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

git pull --rebase origin main

echo "$(date): repo updated from GitHub" >> "$LOG_DIR/repo_update.log"
