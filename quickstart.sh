#!/bin/bash

# Quick start script for Signal Exporter

set -e

echo "=========================================="
echo "Signal Exporter - Quick Start"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  Please edit .env and set your SIGNAL_PHONE_NUMBER"
    echo "    Example: SIGNAL_PHONE_NUMBER=+1234567890"
    echo ""
    read -p "Press Enter to open .env in nano (or edit it manually)..."
    nano .env
fi

echo ""
echo "Checking Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "⚠️  Ollama is not installed!"
    echo "   Install from: https://ollama.ai"
    exit 1
fi

echo "✓ Ollama is installed"

# Check if model exists
if ! ollama list | grep -q "mistral-nemo"; then
    echo ""
    echo "Pulling mistral-nemo model (this may take a few minutes)..."
    ollama pull mistral-nemo
fi

echo "✓ Ollama model is ready"
echo ""

# Build Docker image
echo "Building Docker image..."
docker-compose build

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Register with Signal:"
echo "   docker-compose run --rm privacy-summarizer python -m src.main setup"
echo ""
echo "2. Check status:"
echo "   docker-compose run --rm privacy-summarizer python -m src.main status"
echo ""
echo "3. Start the daemon:"
echo "   docker-compose up -d"
echo ""
echo "4. View logs:"
echo "   docker-compose logs -f"
echo ""
echo "For more commands, see README.md"
echo ""
