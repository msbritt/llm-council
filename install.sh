#!/bin/bash

# LLM Council - Install script
set -e

echo "Installing LLM Council dependencies..."
echo ""

# Check for uv
if ! command -v uv &>/dev/null; then
  echo "Error: 'uv' is not installed."
  echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# Check for node/npm
if ! command -v npm &>/dev/null; then
  echo "Error: 'npm' is not installed."
  echo "Install Node.js from https://nodejs.org"
  exit 1
fi

# Backend
echo "Installing Python dependencies (uv sync)..."
uv sync
echo "  Done."
echo ""

# Frontend
echo "Installing frontend dependencies (npm install)..."
cd frontend && npm install
cd ..
echo "  Done."
echo ""

# .env reminder
if [ ! -f .env ]; then
  echo "Warning: No .env file found."
  echo "Create one with:"
  echo "  echo 'OPENROUTER_API_KEY=your_key_here' > .env"
  echo ""
fi

echo "Install complete. Run ./start.sh to launch."
