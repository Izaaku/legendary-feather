#!/bin/bash
PORT="${PORT:-5000}"
exec gunicorn --worker-class gevent -w 1 --bind "0.0.0.0:$PORT" --timeout 120 app.main:app
