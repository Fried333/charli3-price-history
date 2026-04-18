#!/usr/bin/env python3
"""Crawl Charli3 oracle on-chain data and index all historical prices.

Scans the Charli3 oracle address via Kupo for all UTxOs (spent + unspent),
decodes C3AS (Asset State) datums to extract price + timestamp, and stores
them in SQLite for fast querying.

Supports: ADA/USD, BTC/USD, USDM/ADA feeds on preprod.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone

import cbor2
import requests

# Charli3 oracle address (preprod) — all feeds share this address
ORACLE_ADDRESS = "addr_test1wq3pacs7jcrlwehpuy3ryj8kwvsqzjp9z6dpmx8txnr0vkq6vqeuu"

# Feed policy IDs (preprod)
FEEDS = {
    "ADA/USD": "886dcb2363e160c944e63cf544ce6f6265b22ef7c4e2478dd975078e",
    "BTC/USD": "43d766bafc64c96754353e9686fac6130990a4f8568b3a2f76e2643f",
    "USDM/ADA": "fcc738fa9ae006bc8de82385ff3457a2817ccc4eaa5ce53a61334674",
}

# C3AS = Charli3 Asset State (contains price data)
C3AS_HEX = "43334153"

KUPO_URL = "http://35.209.192.203:1442"
DB_PATH = "prices.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed TEXT NOT NULL,
            price REAL NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            valid_from_ms INTEGER NOT NULL,
            valid_to_ms INTEGER NOT NULL,
            datum_hash TEXT,
            tx_id TEXT,
            slot INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(feed, datum_hash)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feed_ts ON prices(feed, timestamp_ms)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_state (
            feed TEXT PRIMARY KEY,
            last_slot INTEGER DEFAULT 0,
            last_crawl TEXT
        )
    """)
    conn.commit()
    return conn


def decode_c3as_datum(datum_hex):
    """Decode a Charli3 C3AS datum to extract price and timestamps.

    Structure: Tag(121, [Tag(123, [{0: price_raw, 1: valid_from_ms, 2: valid_to_ms}])])
    Price is in millionths (divide by 1e6 for dollars).
    """
    try:
        data = cbor2.loads(bytes.fromhex(datum_hex))
        if not hasattr(data, 'value'):
            return None
        inner = data.value
        if isinstance(inner, list) and len(inner) > 0:
            inner2 = inner[0]
            if hasattr(inner2, 'value') and isinstance(inner2.value, list):
                m = inner2.value[0]
                if isinstance(m, dict) and 0 in m:
                    return {
                        'price': m[0] / 1e6,
                        'valid_from_ms': m.get(1, 0),
                        'valid_to_ms': m.get(2, 0),
                    }
    except Exception:
        pass
    return None


def fetch_oracle_utxos(policy_id, unspent_only=False):
    """Fetch UTxOs at the oracle address, filter by policy ID client-side."""
    url = f"{KUPO_URL}/matches/{ORACLE_ADDRESS}"
    if unspent_only:
        url += "?unspent"

    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        all_utxos = r.json()
        # Filter by policy ID in assets
        filtered = []
        for u in all_utxos:
            assets = u.get("value", {}).get("assets", {})
            if any(policy_id in k for k in assets.keys()):
                filtered.append(u)
        return filtered
    except Exception as e:
        print(f"  Kupo error: {e}")
        return []


def fetch_datum(datum_hash):
    """Fetch a datum by hash from Kupo."""
    try:
        r = requests.get(f"{KUPO_URL}/datums/{datum_hash}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("datum")
    except Exception:
        pass
    return None


def crawl_feed(conn, feed_name, policy_id):
    """Crawl all price updates for a single feed."""
    print(f"\nCrawling {feed_name} (policy: {policy_id[:16]}...)")

    utxos = fetch_oracle_utxos(policy_id)
    print(f"  Found {len(utxos)} UTxOs")

    new_prices = 0
    for u in utxos:
        # Only process C3AS tokens (asset state with price)
        assets = u.get("value", {}).get("assets", {})
        has_c3as = any(C3AS_HEX in k for k in assets.keys())
        if not has_c3as:
            continue

        datum_hash = u.get("datum_hash")
        if not datum_hash:
            continue

        # Check if already indexed
        exists = conn.execute(
            "SELECT 1 FROM prices WHERE feed=? AND datum_hash=?",
            (feed_name, datum_hash)
        ).fetchone()
        if exists:
            continue

        # Fetch and decode datum
        datum_hex = fetch_datum(datum_hash)
        if not datum_hex:
            continue

        price_data = decode_c3as_datum(datum_hex)
        if not price_data:
            continue

        # Store
        tx_id = u.get("transaction_id")
        slot = u.get("slot_no") or u.get("created_at", {}).get("slot_no")

        conn.execute(
            """INSERT OR IGNORE INTO prices
               (feed, price, timestamp_ms, valid_from_ms, valid_to_ms, datum_hash, tx_id, slot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (feed_name, price_data['price'],
             price_data['valid_from_ms'], price_data['valid_from_ms'],
             price_data['valid_to_ms'], datum_hash, tx_id, slot)
        )
        new_prices += 1

        ts = datetime.fromtimestamp(price_data['valid_from_ms'] / 1000, tz=timezone.utc)
        print(f"  ${price_data['price']:.6f} at {ts.strftime('%Y-%m-%d %H:%M UTC')}")

    conn.execute(
        """INSERT OR REPLACE INTO crawl_state (feed, last_slot, last_crawl)
           VALUES (?, ?, ?)""",
        (feed_name, 0, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    print(f"  {new_prices} new prices indexed")
    return new_prices


def crawl_all():
    """Crawl all configured feeds."""
    conn = init_db()
    total = 0

    for feed_name, policy_id in FEEDS.items():
        total += crawl_feed(conn, feed_name, policy_id)
        time.sleep(0.5)

    # Summary
    for feed_name in FEEDS:
        count = conn.execute("SELECT COUNT(*) FROM prices WHERE feed=?", (feed_name,)).fetchone()[0]
        latest = conn.execute(
            "SELECT price, timestamp_ms FROM prices WHERE feed=? ORDER BY timestamp_ms DESC LIMIT 1",
            (feed_name,)
        ).fetchone()
        if latest:
            ts = datetime.fromtimestamp(latest[1] / 1000, tz=timezone.utc)
            print(f"\n{feed_name}: {count} prices, latest ${latest[0]:.6f} at {ts.strftime('%Y-%m-%d %H:%M UTC')}")
        else:
            print(f"\n{feed_name}: {count} prices")

    conn.close()
    return total


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="Continuous mode: crawl every 5 minutes")
    args = ap.parse_args()

    print("Charli3 Price History Crawler")
    print("=" * 40)
    crawl_all()

    if args.watch:
        print("\nWatch mode — crawling every 5 minutes (Ctrl+C to stop)")
        while True:
            time.sleep(300)
            print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] Recrawling...")
            crawl_all()
