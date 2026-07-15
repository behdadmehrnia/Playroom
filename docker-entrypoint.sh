#!/bin/bash
set -e

# Check if data volume is mounted (warn if not)
if [ ! -d "/app/textbook_service/data" ] || [ -z "$(ls -A /app/textbook_service/data 2>/dev/null)" ]; then
    echo "WARNING: /app/textbook_service/data appears empty or not mounted."
    echo "For data persistence, mount a volume at /app/textbook_service/data"
    echo "Example: docker run -v yarkids-data:/app/textbook_service/data ..."
fi

# Start textbook-service in background (from /app with full module path)
cd /app
uvicorn textbook_service.app.main:app --host 0.0.0.0 --port 8080 &
TEXTBOOK_PID=$!

# Wait for textbook-service to be ready
for i in {1..30}; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "textbook-service ready"
        break
    fi
    sleep 1
done

# Start main API
cd /app/api
uvicorn main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Trap signals for graceful shutdown
trap "kill $TEXTBOOK_PID $API_PID; wait $TEXTBOOK_PID $API_PID" SIGTERM SIGINT

# Wait for both processes
wait $TEXTBOOK_PID $API_PID