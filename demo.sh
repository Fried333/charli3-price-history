#!/bin/bash
# Run this in a terminal while screen recording — shows the API in action
clear
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Charli3 Price Oracle — Live API Demo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
sleep 2

echo "▸ Get latest ADA/USD price (one HTTP call):"
echo
echo "  curl https://86-107-168-44.sslip.io/api/price/ADA-USD"
echo
sleep 1
curl -s https://86-107-168-44.sslip.io/api/price/ADA-USD | python3 -m json.tool
sleep 3

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▸ Historical prices:"
echo
echo "  curl https://86-107-168-44.sslip.io/api/history/ADA-USD?limit=5"
echo
sleep 1
curl -s "https://86-107-168-44.sslip.io/api/history/ADA-USD?limit=5" | python3 -m json.tool
sleep 3

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▸ Price at a specific time (for DeFi settlement):"
echo
echo "  curl https://86-107-168-44.sslip.io/api/price-at/ADA-USD?time=2026-04-17T12:00:00Z"
echo
sleep 1
curl -s "https://86-107-168-44.sslip.io/api/price-at/ADA-USD?time=2026-04-17T12:00:00Z" | python3 -m json.tool
sleep 3

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▸ Oracle accuracy vs market (CoinGecko):"
echo
sleep 1
curl -s https://86-107-168-44.sslip.io/api/compare/ADA-USD | python3 -m json.tool
sleep 3

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▸ Convert 10,000 ADA to USD using oracle price:"
echo
sleep 1
curl -s "https://86-107-168-44.sslip.io/api/convert?amount=10000&from_currency=ADA&to_currency=USD" | python3 -m json.tool
sleep 3

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "▸ Oracle health metrics:"
echo
sleep 1
curl -s https://86-107-168-44.sslip.io/api/health/ADA-USD | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'  Total updates: {d[\"total_updates\"]}')
print(f'  Avg interval:  {d[\"avg_update_interval_minutes\"]} minutes')
print(f'  Staleness:     {d[\"current_staleness_minutes\"]} minutes')
print(f'  Stale:         {d[\"is_stale\"]}')
"
sleep 3

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ 9 API endpoints"
echo "  ✓ Live at https://86-107-168-44.sslip.io"
echo "  ✓ 100% of Charli3 preprod oracle history indexed"
echo "  ✓ Zero setup — one HTTP call from any language"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
