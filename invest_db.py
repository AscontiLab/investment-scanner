"""SQLite-Datenbankmodul fuer den Investment Scanner."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "invest.db"


def _connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Erstellt Tabellen falls nicht vorhanden."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanned_at TEXT NOT NULL,
                source_count INTEGER DEFAULT 0,
                new_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE NOT NULL,
                source TEXT,
                company TEXT,
                title TEXT,
                location TEXT,
                region TEXT,
                price INTEGER,
                area_m2 INTEGER,
                price_per_m2 REAL,
                category TEXT,
                category_code TEXT,
                status TEXT,
                rented TEXT,
                monument TEXT,
                auction_number TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                ki_score REAL,
                ki_headline TEXT,
                ki_analysis TEXT,
                ki_strengths TEXT,
                ki_weaknesses TEXT,
                ki_recommendation TEXT,
                ki_risk TEXT,
                ki_scored_at TEXT
            )
        """)
        conn.commit()


def log_scan_run(source_count: int, new_count: int) -> int:
    """Loggt einen Scan-Run, gibt run_id zurueck."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (scanned_at, source_count, new_count) VALUES (?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d"), source_count, new_count),
        )
        conn.commit()
        return cur.lastrowid


def upsert_property(prop: dict) -> bool:
    """Insert oder Update eines Objekts. Returns True wenn neu."""
    today = datetime.now().strftime("%Y-%m-%d")
    link = prop.get("link")
    if not link:
        raise ValueError("Property muss 'link' enthalten")

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM properties WHERE link = ?", (link,)
        ).fetchone()

        if existing:
            # Update: last_seen und alle anderen Felder aktualisieren
            fields = [
                "source", "company", "title", "location", "region",
                "price", "area_m2", "price_per_m2", "category", "category_code",
                "status", "rented", "monument", "auction_number",
            ]
            updates = ["last_seen = ?"]
            values = [today]
            for f in fields:
                if f in prop:
                    updates.append(f"{f} = ?")
                    values.append(prop[f])
            values.append(link)
            conn.execute(
                f"UPDATE properties SET {', '.join(updates)} WHERE link = ?",
                values,
            )
            conn.commit()
            return False
        else:
            # Insert: first_seen und last_seen auf heute
            columns = [
                "link", "source", "company", "title", "location", "region",
                "price", "area_m2", "price_per_m2", "category", "category_code",
                "status", "rented", "monument", "auction_number",
                "first_seen", "last_seen",
            ]
            prop["first_seen"] = today
            prop["last_seen"] = today
            values = [prop.get(c) for c in columns]
            placeholders = ", ".join(["?"] * len(columns))
            col_names = ", ".join(columns)
            conn.execute(
                f"INSERT INTO properties ({col_names}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
            return True


def get_all_properties(
    status: str = None,
    category: str = None,
    region: str = None,
    min_score: float = None,
) -> list[dict]:
    """Alle Objekte mit optionalen Filtern."""
    query = "SELECT * FROM properties WHERE 1=1"
    params = []

    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if category is not None:
        query += " AND category = ?"
        params.append(category)
    if region is not None:
        query += " AND region = ?"
        params.append(region)
    if min_score is not None:
        query += " AND ki_score >= ?"
        params.append(min_score)

    query += " ORDER BY last_seen DESC, ki_score DESC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_unscored_properties() -> list[dict]:
    """Objekte ohne KI-Score."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM properties WHERE ki_score IS NULL ORDER BY last_seen DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def save_ki_score(
    link: str,
    score: float,
    headline: str,
    analysis: str,
    strengths: str,
    weaknesses: str,
    recommendation: str,
    risk: str,
):
    """Speichert KI-Bewertung fuer ein Objekt."""
    today = datetime.now().strftime("%Y-%m-%d")
    with _connect() as conn:
        conn.execute(
            """UPDATE properties
               SET ki_score = ?, ki_headline = ?, ki_analysis = ?,
                   ki_strengths = ?, ki_weaknesses = ?, ki_recommendation = ?,
                   ki_risk = ?, ki_scored_at = ?
               WHERE link = ?""",
            (score, headline, analysis, strengths, weaknesses, recommendation, risk, today, link),
        )
        conn.commit()


def get_stats() -> dict:
    """Statistiken: total, new_today, avg_score, nachverkauf_count, by_category, by_region."""
    today = datetime.now().strftime("%Y-%m-%d")

    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE first_seen = ?", (today,)
        ).fetchone()[0]
        avg_score = conn.execute(
            "SELECT AVG(ki_score) FROM properties WHERE ki_score IS NOT NULL"
        ).fetchone()[0]
        nachverkauf_count = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE status = 'nachverkauf'"
        ).fetchone()[0]

        by_category_rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM properties GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        by_category = {row["category"] or "Unbekannt": row["cnt"] for row in by_category_rows}

        by_region_rows = conn.execute(
            "SELECT region, COUNT(*) as cnt FROM properties GROUP BY region ORDER BY cnt DESC"
        ).fetchall()
        by_region = {row["region"] or "Unbekannt": row["cnt"] for row in by_region_rows}

    return {
        "total": total,
        "new_today": new_today,
        "avg_score": round(avg_score, 1) if avg_score else None,
        "nachverkauf_count": nachverkauf_count,
        "by_category": by_category,
        "by_region": by_region,
    }


# DB beim Import initialisieren
init_db()
