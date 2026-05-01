#!/bin/bash
PORT="${PORT:-5000}"
# Use the gevent-websocket worker class so Flask-SocketIO can handle WebSocket
# upgrades. With plain `gevent`, the upgrade fails with:
#   RuntimeError: The gevent-websocket server is not configured appropriately
# Falling back to long-polling worked but added latency to every request and
# was causing translation timeouts on cold starts.
exec gunicorn \
  --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
  -w 1 \
  --bind "0.0.0.0:$PORT" \
  --timeout 120 \
  --keep-alive 5 \
  app.main:app
