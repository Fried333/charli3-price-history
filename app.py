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


@app.get("/api/price-at/{feed}")
def price_at_time(feed: str, time: str = Query(..., description="ISO timestamp or unix ms")):
    """Get the closest oracle price to a specific timestamp."""
    feed_name = feed.upper().replace("-", "/")
    if feed_name not in FEEDS:
        return JSONResponse({"error": f"Unknown feed. Available: {FEEDS}"}, 404)

    try:
        if time.isdigit():
            target_ms = int(time)
        else:
            target_ms = int(datetime.fromisoformat(time.replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        return JSONResponse({"error": "Invalid time format. Use ISO timestamp or unix ms."}, 400)

    conn = get_db()
    row = conn.execute(
        """SELECT price, timestamp_ms, datum_hash, tx_id,
                  ABS(timestamp_ms - ?) as distance
           FROM prices WHERE feed=? ORDER BY distance ASC LIMIT 1""",
        (target_ms, feed_name)
    ).fetchone()
    conn.close()

    if not row:
        return JSONResponse({"error": "No price data available"}, 404)

    return {
        "feed": feed_name,
        "price": row[0],
        "timestamp": datetime.fromtimestamp(row[1] / 1000, tz=timezone.utc).isoformat(),
        "requested_time": datetime.fromtimestamp(target_ms / 1000, tz=timezone.utc).isoformat(),
        "distance_seconds": round(row[4] / 1000),
        "datum_hash": row[2],
        "tx_id": row[3],
        "source": "charli3",
    }


@app.get("/api/export/{feed}")
def export_csv(feed: str):
    """Download all historical prices as CSV."""
    feed_name = feed.upper().replace("-", "/")
    if feed_name not in FEEDS:
        return JSONResponse({"error": f"Unknown feed. Available: {FEEDS}"}, 404)

    conn = get_db()
    rows = conn.execute(
        "SELECT price, timestamp_ms, datum_hash, tx_id FROM prices WHERE feed=? ORDER BY timestamp_ms ASC",
        (feed_name,)
    ).fetchall()
    conn.close()

    lines = ["timestamp,price,datum_hash,tx_id"]
    for r in rows:
        ts = datetime.fromtimestamp(r[1] / 1000, tz=timezone.utc).isoformat()
        lines.append(f"{ts},{r[0]},{r[2]},{r[3]}")

    from fastapi.responses import Response
    return Response(
        content="\n".join(lines),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={feed_name.replace('/', '-')}_prices.csv"},
    )


@app.get("/api/convert")
def convert(amount: float = Query(...), from_currency: str = Query("ADA"), to_currency: str = Query("USD")):
    """Convert between currencies using Charli3 oracle prices."""
    feed_map = {
        ("ADA", "USD"): ("ADA/USD", False),
        ("USD", "ADA"): ("ADA/USD", True),
        ("BTC", "USD"): ("BTC/USD", False),
        ("USD", "BTC"): ("BTC/USD", True),
    }
    key = (from_currency.upper(), to_currency.upper())
    if key not in feed_map:
        return JSONResponse({"error": f"Unsupported pair. Available: {list(feed_map.keys())}"}, 400)

    feed_name, invert = feed_map[key]
    conn = get_db()
    row = conn.execute(
        "SELECT price, timestamp_ms FROM prices WHERE feed=? ORDER BY timestamp_ms DESC LIMIT 1",
        (feed_name,)
    ).fetchone()
    conn.close()

    if not row:
        return JSONResponse({"error": "No price data"}, 404)

    rate = 1 / row[0] if invert else row[0]
    result = amount * rate

    return {
        "from": {"amount": amount, "currency": from_currency.upper()},
        "to": {"amount": round(result, 6), "currency": to_currency.upper()},
        "rate": round(rate, 6),
        "oracle_price": row[0],
        "feed": feed_name,
        "timestamp": datetime.fromtimestamp(row[1] / 1000, tz=timezone.utc).isoformat(),
        "source": "charli3",
    }


@app.get("/api/health/{feed}")
def feed_health(feed: str):
    """Oracle health metrics — update frequency, gaps, reliability."""
    feed_name = feed.upper().replace("-", "/")
    if feed_name not in FEEDS:
        return JSONResponse({"error": f"Unknown feed. Available: {FEEDS}"}, 404)

    conn = get_db()
    rows = conn.execute(
        "SELECT timestamp_ms FROM prices WHERE feed=? ORDER BY timestamp_ms ASC",
        (feed_name,)
    ).fetchall()
    conn.close()

    if len(rows) < 2:
        return {"feed": feed_name, "total_updates": len(rows), "health": "insufficient_data"}

    timestamps = [r[0] for r in rows]
    gaps = [(timestamps[i+1] - timestamps[i]) / 1000 / 60 for i in range(len(timestamps)-1)]
    now_ms = int(time.time() * 1000)
    staleness = (now_ms - timestamps[-1]) / 1000 / 60

    span_minutes = (timestamps[-1] - timestamps[0]) / 1000 / 60

    # Updates in last 24h
    day_ago = now_ms - 86400000
    updates_24h = sum(1 for ts in timestamps if ts > day_ago)

    # Hourly update counts for chart
    hourly = {}
    for ts in timestamps:
        hour = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:00')
        hourly[hour] = hourly.get(hour, 0) + 1

    return {
        "feed": feed_name,
        "total_updates": len(timestamps),
        "updates_last_24h": updates_24h,
        "current_staleness_minutes": round(staleness, 1),
        "is_stale": staleness > 120,
        "avg_update_interval_minutes": round(sum(gaps) / len(gaps), 1),
        "min_gap_minutes": round(min(gaps), 1),
        "max_gap_minutes": round(max(gaps), 1),
        "span_hours": round(span_minutes / 60, 1),
        "hourly_updates": hourly,
    }


@app.get("/api/compare/{feed}")
def compare_price(feed: str):
    """Compare Charli3 oracle price vs CoinGecko market price."""
    feed_name = feed.upper().replace("-", "/")
    if feed_name not in FEEDS:
        return JSONResponse({"error": f"Unknown feed. Available: {FEEDS}"}, 404)

    conn = get_db()
    row = conn.execute(
        "SELECT price, timestamp_ms FROM prices WHERE feed=? ORDER BY timestamp_ms DESC LIMIT 1",
        (feed_name,)
    ).fetchone()
    conn.close()

    if not row:
        return JSONResponse({"error": "No oracle price available"}, 404)

    oracle_price = row[0]
    oracle_ts = row[1]

    # Fetch market price from CoinGecko
    market_price = None
    try:
        import requests as req
        cg_ids = {"ADA/USD": "cardano", "BTC/USD": "bitcoin", "USDM/ADA": None}
        cg_id = cg_ids.get(feed_name)
        if cg_id:
            r = req.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd", timeout=10)
            if r.status_code == 200:
                market_price = r.json().get(cg_id, {}).get("usd")
    except Exception:
        pass

    result = {
        "feed": feed_name,
        "oracle": {"price": oracle_price, "timestamp": datetime.fromtimestamp(oracle_ts / 1000, tz=timezone.utc).isoformat(), "source": "charli3"},
        "market": {"price": market_price, "source": "coingecko"} if market_price else None,
    }

    if market_price and oracle_price:
        deviation = abs(oracle_price - market_price) / market_price * 100
        result["deviation_percent"] = round(deviation, 4)
        result["oracle_accurate"] = deviation < 1.0

    return result


@app.get("/")
def index():
    return FileResponse(str(Path(__file__).parent / "index.html"))
