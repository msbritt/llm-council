#!/bin/bash

# LLM Council - Start script

echo "Starting LLM Council..."
echo ""

# Stop any existing servers
echo "Checking for existing servers..."
BACKEND_PID=$(lsof -ti:8001)
FRONTEND_PID=$(lsof -ti:5173)

if [ -n "$BACKEND_PID" ]; then
  echo "  Stopping existing backend (PID: $BACKEND_PID)..."
  kill $BACKEND_PID 2>/dev/null
  sleep 1
fi

if [ -n "$FRONTEND_PID" ]; then
  echo "  Stopping existing frontend (PID: $FRONTEND_PID)..."
  kill $FRONTEND_PID 2>/dev/null
  sleep 1
fi

echo ""

# Start backend
echo "Starting backend on http://localhost:8001..."
uv run python -m backend.main &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend
echo "Starting frontend on http://localhost:5173..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✓ LLM Council is running!"
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
