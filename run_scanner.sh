#!/bin/bash
# Investment Scanner — Wrapper-Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

mkdir -p logs
python3 investment_scanner.py 2>&1 | tee logs/scanner_$(date +%Y-%m-%d).log
