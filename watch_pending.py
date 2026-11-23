#!/usr/bin/env python3
"""Middleman watcher: prints one JSON line per message waiting for a host session."""
import json
import os
import time
import urllib.request

LOCAL_PORT = int(os.environ.get("BRIDGE_LOCAL_PORT", "8788"))

while True:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{LOCAL_PORT}/pending", timeout=5) as response:
            for message in json.load(response)["pending"]:
                print(json.dumps(message), flush=True)
    except Exception as error:
        print(f"watcher error: {error}", flush=True)
        time.sleep(10)
    time.sleep(2)
