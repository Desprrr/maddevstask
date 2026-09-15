#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Seeding demo data (idempotent, skips if data already exists)..."
python -m app.seed

echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
