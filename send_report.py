#!/usr/bin/env python3
"""Sendet den neuesten Investment-Scanner-Report per E-Mail."""

import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

CREDS_FILE = Path.home() / ".stock_scanner_credentials"


def load_creds() -> dict:
    creds = {}
    if not CREDS_FILE.exists():
        print(f"Fehler: Credentials-Datei fehlt: {CREDS_FILE}", file=sys.stderr)
        return {}
    with open(CREDS_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds


def require_keys(creds: dict, keys: list[str]) -> bool:
    missing = [k for k in keys if not creds.get(k)]
    if missing:
        print(f"Fehler: Fehlende Credentials: {', '.join(missing)}", file=sys.stderr)
        return False
    return True


def find_latest_report() -> Path | None:
    output_dir = Path(__file__).parent / "output"
    reports = sorted(output_dir.glob("*/investments.html"), reverse=True)
    return reports[0] if reports else None


def main() -> int:
    creds = load_creds()
    if not require_keys(creds, ["GMAIL_USER", "GMAIL_APP_PASSWORD", "GMAIL_RECIPIENT"]):
        return 1
    user = creds["GMAIL_USER"]
    password = creds["GMAIL_APP_PASSWORD"]
    recipient = creds["GMAIL_RECIPIENT"]

    report_path = find_latest_report()
    if not report_path:
        print("Kein Report gefunden.")
        return 1

    report_date = report_path.parent.name
    html_content = report_path.read_text(encoding="utf-8")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Investment Scanner — {report_date}"
    msg["From"] = user
    msg["To"] = recipient
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    print(f"Sende Report vom {report_date} an {recipient} ...")
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(user, recipient, msg.as_string())

    print("✓ Mail gesendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
