#!/usr/bin/env python3
"""Charli3 Price History API — REST + live ticker.

Serves historical and current oracle prices from the indexed SQLite DB.
Run crawler.py first to populate data.
"""
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

DB_PATH = str(Path(__file__).parent / "prices.db")
app = FastAPI(title="Charli3 Price History", description="Historical oracle price data from Charli3 on-chain feeds")

FEEDS = ["ADA/USD", "BTC/USD", "USDM/ADA"]


def get_db():
    return sqlite3.connect(DB_PATH)


@app.get("/api/feeds")
def list_feeds():
    """List all available price feeds with latest price."""
    conn = get_db()
    feeds = []
    for feed in FEEDS:
        row = conn.execute(
            "SELECT price, timestamp_ms FROM prices WHERE feed=? ORDER BY timestamp_ms DESC LIMIT 1",
            (feed,)
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM prices WHERE feed=?", (feed,)).fetchone()[0]
        oldest = conn.execute(
            "SELECT timestamp_ms FROM prices WHERE feed=? ORDER BY timestamp_ms ASC LIMIT 1",
            (feed,)
        ).fetchone()
        feeds.append({
            "feed": feed,
            "latest_price": row[0] if row else None,
            "latest_timestamp": datetime.fromtimestamp(row[1] / 1000, tz=timezone.utc).isoformat() if row else None,
            "total_updates": count,
            "oldest_timestamp": datetime.fromtimestamp(oldest[0] / 1000, tz=timezone.utc).isoformat() if oldest else None,
        })
    conn.close()
    return {"feeds": feeds, "source": "charli3", "network": "preprod"}


@app.get("/api/price/{feed}")
def latest_price(feed: str):
    """Get the latest price for a feed. Feed format: ADA-USD, BTC-USD, USDM-ADA."""
    feed_name = feed.upper().replace("-", "/")
    if feed_name not in FEEDS:
        return JSONResponse({"error": f"Unknown feed. Available: {FEEDS}"}, 404)

    conn = get_db()
    row = conn.execute(
        "SELECT price, timestamp_ms, valid_from_ms, valid_to_ms, datum_hash, tx_id FROM prices WHERE feed=? ORDER BY timestamp_ms DESC LIMIT 1",
        (feed_name,)
    ).fetchone()
    conn.close()

    if not row:
        return JSONResponse({"error": "No price data available"}, 404)

    now_ms = int(time.time() * 1000)
    age_seconds = (now_ms - row[1]) / 1000

    return {
        "feed": feed_name,
        "price": row[0],
        "timestamp": datetime.fromtimestamp(row[1] / 1000, tz=timezone.utc).isoformat(),
        "valid_from": datetime.fromtimestamp(row[2] / 1000, tz=timezone.utc).isoformat(),
        "valid_to": datetime.fromtimestamp(row[3] / 1000, tz=timezone.utc).isoformat(),
        "age_seconds": round(age_seconds),
        "stale": age_seconds > 3600,
        "datum_hash": row[4],
        "tx_id": row[5],
        "source": "charli3",
        "network": "preprod",
    }


@app.get("/api/history/{feed}")
def price_history(
    feed: str,
    limit: int = Query(100, ge=1, le=1000),
    from_ts: str = Query(None, description="ISO timestamp or unix ms"),
    to_ts: str = Query(None, description="ISO timestamp or unix ms"),
):
    """Get historical prices for a feed."""
    feed_name = feed.upper().replace("-", "/")
    if feed_name not in FEEDS:
        return JSONResponse({"error": f"Unknown feed. Available: {FEEDS}"}, 404)

    conn = get_db()
    query = "SELECT price, timestamp_ms, datum_hash, tx_id FROM prices WHERE feed=?"
    params = [feed_name]

    if from_ts:
        try:
            from_ms = int(from_ts) if from_ts.isdigit() else int(datetime.fromisoformat(from_ts.replace('Z', '+00:00')).timestamp() * 1000)
            query += " AND timestamp_ms >= ?"
            params.append(from_ms)
        except ValueError:
            pass

    if to_ts:
        try:
            to_ms = int(to_ts) if to_ts.isdigit() else int(datetime.fromisoformat(to_ts.replace('Z', '+00:00')).timestamp() * 1000)
            query += " AND timestamp_ms <= ?"
            params.append(to_ms)
        except ValueError:
            pass

    query += " ORDER BY timestamp_ms DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    prices = [{
        "price": r[0],
        "timestamp": datetime.fromtimestamp(r[1] / 1000, tz=timezone.utc).isoformat(),
        "timestamp_ms": r[1],
        "datum_hash": r[2],
        "tx_id": r[3],
    } for r in rows]

    # Reverse for chronological order
    prices.reverse()

    return {
        "feed": feed_name,
        "count": len(prices),
        "prices": prices,
        "source": "charli3",
        "network": "preprod",
    }


@app.get("/api/stats")
def stats():
    """Overall oracle statistics."""
    conn = get_db()
    result = {"feeds": {}, "source": "charli3", "network": "preprod"}

    for feed in FEEDS:
        rows = conn.execute(
            """SELECT COUNT(*), MIN(price), MAX(price), AVG(price),
                      MIN(timestamp_ms), MAX(timestamp_ms)
               FROM prices WHERE feed=?""",
            (feed,)
        ).fetchone()
        if rows[0] > 0:
            # Calculate average update frequency
            if rows[0] > 1:
                span_ms = rows[5] - rows[4]
                avg_interval = span_ms / (rows[0] - 1) / 1000 / 60  # minutes
            else:
                avg_interval = None

            result["feeds"][feed] = {
                "total_updates": rows[0],
                "min_price": rows[1],
                "max_price": rows[2],
                "avg_price": round(rows[3], 6),
                "first_update": datetime.fromtimestamp(rows[4] / 1000, tz=timezone.utc).isoformat(),
                "last_update": datetime.fromtimestamp(rows[5] / 1000, tz=timezone.utc).isoformat(),
                "avg_update_interval_minutes": round(avg_interval, 1) if avg_interval else None,
            }

    conn.close()
    return result


@app.get("/")
def index():
    return FileResponse(str(Path(__file__).parent / "index.html"))
