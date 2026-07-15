#!/bin/bash
set -e

# Start API service
cd /app/api
exec uvicorn main:app --host 0.0.0.0 --port 8000