#!/bin/bash
echo "Stopping old processes..."
pkill -f "gunicorn" 2>/dev/null
pkill -f "app.py" 2>/dev/null
sleep 2

echo "Starting Gunicorn..."
cd /root/restaurant-ops
source venv/bin/activate
export $(grep -v '^#' /root/restaurant-ops/.env | xargs)

gunicorn \
  --workers 3 \
  --threads 2 \
  --worker-class gthread \
  --bind 0.0.0.0:8082 \
  --timeout 120 \
  --keep-alive 5 \
  --log-level info \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  --daemon \
  app:app

sleep 2
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8082)
echo "HTTP $STATUS"
PID=$(pgrep -f "gunicorn.*app:app" | head -1)
echo "  $PID /root/restaurant-ops/venv/bin/gunicorn app:app"
