#!/usr/bin/env python3
"""
ChakkiMate Render Free Tier Keep-Alive Daemon.
Pings the /ping/ health check endpoint every 9 minutes to keep the Render
instance warm and eliminate the 50-second cold start delay.
"""
import time
import urllib.request
import json
import sys

URL = "https://chakkimate.onrender.com/ping/"
INTERVAL_SECONDS = 540  # 9 minutes (Render sleeps after 15 min)

def ping_service():
    try:
        req = urllib.request.Request(
            URL,
            headers={'User-Agent': 'ChakkiMate-Warmup-Bot/1.0'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            status = response.getcode()
            body = response.read().decode('utf-8')
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] PING {URL} -> HTTP {status}: {body}")
            return status == 200
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] PING {URL} ERROR: {e}")
        return False

def main():
    print(f"Starting ChakkiMate Keep-Alive Ping Service for {URL}...")
    print(f"Interval: every {INTERVAL_SECONDS} seconds (9 minutes). Press Ctrl+C to stop.")
    while True:
        ping_service()
        time.sleep(INTERVAL_SECONDS)

if __name__ == '__main__':
    main()
