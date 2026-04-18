"""Prediction market module — oracle-settled price predictions.

Users create predictions like "ADA will be above $0.26 by April 19 12:00 UTC"
The Charli3 oracle settles them automatically at the deadline.
"""
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "prices.db")


def init_predictions_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY,
            creator TEXT NOT NULL,
            feed TEXT NOT NULL DEFAULT 'ADA/USD',
            direction TEXT NOT NULL,
            target_price REAL NOT NULL,
            deadline_ms INTEGER NOT NULL,
            stake_ada REAL DEFAULT 0,
            challenger TEXT,
            status TEXT DEFAULT 'open',
            settlement_price REAL,
            settlement_time TEXT,
            winner TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_prediction(creator, feed, direction, target_price, deadline_iso, stake_ada=0):
    """Create a new prediction."""
    pred_id = str(uuid.uuid4())[:8]
    deadline_ms = int(datetime.fromisoformat(deadline_iso.replace('Z', '+00:00')).timestamp() * 1000)

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO predictions (id, creator, feed, direction, target_price, deadline_ms, stake_ada)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (pred_id, creator, feed.upper().replace("-", "/"), direction, target_price, deadline_ms, stake_ada)
    )
    conn.commit()
    conn.close()
    return pred_id


def challenge_prediction(pred_id, challenger):
    """Accept a prediction challenge (take the other side)."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT status FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": "Prediction not found"}
    if row[0] != 'open':
        conn.close()
        return {"error": f"Prediction is {row[0]}, not open"}

    conn.execute("UPDATE predictions SET challenger=?, status='active' WHERE id=?", (challenger, pred_id))
    conn.commit()
    conn.close()
    return {"status": "challenged"}


def settle_predictions():
    """Check all active predictions and settle any past their deadline."""
    conn = sqlite3.connect(DB_PATH)
    now_ms = int(time.time() * 1000)

    active = conn.execute(
        "SELECT id, feed, direction, target_price, deadline_ms, creator, challenger FROM predictions WHERE status='active' AND deadline_ms <= ?",
        (now_ms,)
    ).fetchall()

    settled = []
    for pred in active:
        pred_id, feed, direction, target, deadline, creator, challenger = pred

        # Get closest oracle price to the deadline
        price_row = conn.execute(
            """SELECT price, timestamp_ms FROM prices
               WHERE feed=? ORDER BY ABS(timestamp_ms - ?) ASC LIMIT 1""",
            (feed, deadline)
        ).fetchone()

        if not price_row:
            continue

        oracle_price = price_row[0]
        hit = (direction == 'above' and oracle_price >= target) or \
              (direction == 'below' and oracle_price <= target)
        winner = creator if hit else (challenger or 'market')

        conn.execute(
            """UPDATE predictions SET status='settled', settlement_price=?,
               settlement_time=?, winner=? WHERE id=?""",
            (oracle_price, datetime.now(timezone.utc).isoformat(), winner, pred_id)
        )
        settled.append({
            'id': pred_id,
            'oracle_price': oracle_price,
            'target': target,
            'direction': direction,
            'hit': hit,
            'winner': winner,
        })

    conn.commit()
    conn.close()
    return settled


def list_predictions(status=None):
    conn = sqlite3.connect(DB_PATH)
    if status:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM predictions ORDER BY created_at DESC").fetchall()
    conn.close()

    cols = ['id', 'creator', 'feed', 'direction', 'target_price', 'deadline_ms',
            'stake_ada', 'challenger', 'status', 'settlement_price', 'settlement_time',
            'winner', 'created_at']
    return [dict(zip(cols, r)) for r in rows]


init_predictions_db()
