#!/bin/bash
cd /root/investment_scanner
python3 investment_scanner.py 2>&1 | tee logs/scanner_$(date +%Y-%m-%d).log
