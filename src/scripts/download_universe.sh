#!/bin/bash
set -e

PROJECT_DIR="/mnt/c/Users/mnday/Stock_Trading_Pipeline"

cd "$PROJECT_DIR"

git pull origin main

echo "$(date): repository updated" >> logs/update.log
