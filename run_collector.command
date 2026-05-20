#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Starting Product Hunt Collector..."
echo

uv run python fetch_producthunt.py

echo
echo "Product Hunt Collector finished successfully."
echo
read -n 1 -s -r -p "Press any key to continue..."
echo
