#!/bin/bash
cd /root/restaurant-ops
# Find and kill the running flask app, excluding our own pid and shell ancestors
for pid in $(ps -eo pid,cmd | awk '/venv\/bin\/python3 ap[p]\.py/ {print $1}'); do
  kill "$pid" 2>/dev/null
done
sleep 2
nohup /root/restaurant-ops/venv/bin/python3 /root/restaurant-ops/app.py > /root/restaurant-ops/logs/ops.log 2>&1 &
disown
sleep 3
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8082
ps -eo pid,cmd | awk '/venv\/bin\/python3 ap[p]\.py/'
