# Charli3 Price History

Historical and real-time oracle price data from Charli3's on-chain feeds on Cardano.

## The Problem

Charli3 operates a pull oracle — prices exist on-chain only when someone requests an update. This means:
- No aggregated price history exists
- Developers can't ask "what was ADA/USD yesterday?"
- No way to chart oracle price data over time
- No simple REST API to get the latest price

## The Solution

This tool crawls Charli3's oracle smart contract on Cardano, decodes every price datum ever posted, and serves them via a simple REST API + live ticker.

### What it does:
1. **Crawls** the Charli3 oracle address on-chain via Kupo
2. **Decodes** CBOR datums (C3AS Asset State) to extract prices + timestamps
3. **Indexes** all historical prices in a local database
4. **Serves** via REST API: `GET /api/price/ADA-USD` → instant price
5. **Displays** live ticker + historical price chart

## Oracle Feeds

| Feed | Oracle Policy ID | Description |
|------|-----------------|-------------|
| ADA/USD | `886dcb23...` | Cardano native token price in USD |
| BTC/USD | `43d766ba...` | Bitcoin price in USD |
| USDM/ADA | `fcc738fa...` | Mehen USDM stablecoin rate |

## Quick Start

```bash
# Install dependencies
pip install fastapi uvicorn cbor2 requests

# Crawl oracle prices from chain
python crawler.py

# Start the API + ticker
uvicorn app:app --host 0.0.0.0 --port 8080

# Open http://localhost:8080
```

## API Endpoints

### Get Latest Price
```bash
curl http://localhost:8080/api/price/ADA-USD
```
```json
{
  "feed": "ADA/USD",
  "price": 0.2573,
  "timestamp": "2026-04-18T04:23:00+00:00",
  "age_seconds": 142,
  "stale": false,
  "source": "charli3",
  "network": "preprod"
}
```

### Get Price History
```bash
curl http://localhost:8080/api/history/ADA-USD?limit=50
```
```json
{
  "feed": "ADA/USD",
  "count": 45,
  "prices": [
    {"price": 0.249140, "timestamp": "2026-04-15T22:16:00+00:00"},
    {"price": 0.252444, "timestamp": "2026-04-16T17:24:00+00:00"},
    ...
  ]
}
```

### List All Feeds
```bash
curl http://localhost:8080/api/feeds
```

### Feed Statistics
```bash
curl http://localhost:8080/api/stats
```

## How It Works

### On-Chain Data Structure

Charli3's oracle stores price data in Plutus inline datums at the oracle address. Each price update creates a UTxO with a C3AS (Asset State) token containing:

```
CBOR: Tag(121, [Tag(123, [{
  0: price_raw,      // Price in millionths (divide by 1e6)
  1: valid_from_ms,  // POSIX timestamp in milliseconds
  2: valid_to_ms     // Expiry timestamp
}])])
```

The crawler reads these datums via Kupo (a chain indexer), decodes the CBOR, and stores the extracted prices.

### Architecture

```
Cardano Blockchain
  └─ Oracle Address (addr_test1wq3pacs...)
       └─ UTxOs with C3AS tokens + inline datums
            │
            ▼
       Kupo (chain indexer)
            │
            ▼
       crawler.py (decode CBOR datums → SQLite)
            │
            ▼
       app.py (FastAPI REST API)
            │
            ▼
       index.html (live ticker + price chart)
```

## Charli3 Oracle Integration

This project reads directly from Charli3's on-chain oracle data. Without Charli3's oracle feeds, this tool would have no data to index or serve. The oracle is the sole data source.

- **Oracle address**: `addr_test1wq3pacs7jcrlwehpuy3ryj8kwvsqzjp9z6dpmx8txnr0vkq6vqeuu`
- **Network**: Cardano Preprod Testnet
- **Chain indexer**: Kupo at `http://35.209.192.203:1442`
- **Data format**: Plutus V3 inline datums (CBOR encoded)

## Tech Stack

- **Python 3.10+**: crawler + API
- **FastAPI**: REST API framework
- **cbor2**: CBOR datum decoding
- **SQLite**: Price storage
- **Vanilla HTML/JS/Canvas**: Frontend (no dependencies)

## License

MIT
