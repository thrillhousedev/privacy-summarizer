#!/bin/bash
# Helper script to link signal-cli as a secondary device

set -e

echo "======================================================================"
echo "Signal Device Linking Helper"
echo "======================================================================"
echo ""
echo "This will generate a QR code you can scan with your iPhone."
echo "Make sure you have qrencode installed: brew install qrencode"
echo ""
echo "Starting linking process (you'll have 60 seconds once QR appears)..."
echo ""

# Check if qrencode is installed first
if ! command -v qrencode &> /dev/null; then
    echo "ERROR: qrencode not found. Install it with: brew install qrencode"
    exit 1
fi

# Run signal-cli link and stream output in real-time
# As soon as we see the URI, display the QR code immediately
docker-compose run --rm privacy-summarizer signal-cli --config /signal-cli-config link -n "signal-exporter" 2>&1 | while IFS= read -r line; do
    # Check if this line contains the linking URI
    if [[ "$line" =~ sgnl://linkdevice ]]; then
        # Extract the URI
        URI=$(echo "$line" | grep -o 'sgnl://linkdevice[^[:space:]]*')

        echo ""
        echo "======================================================================"
        echo "SCAN THIS QR CODE NOW - YOU HAVE 60 SECONDS!"
        echo "======================================================================"
        echo ""
        echo "$URI" | qrencode -t ansiutf8
        echo ""
        echo "======================================================================"
        echo "On your iPhone:"
        echo "1. Open Signal"
        echo "2. Settings → Linked Devices → +"
        echo "3. Scan the QR code above NOW!"
        echo "======================================================================"
        echo ""
        echo "Waiting for you to scan (will timeout in ~60 seconds)..."
    fi
    # Still show the line for debugging
    echo "$line" >&2
done
