#!/usr/bin/env python3
"""Prints one JSON line per new Slack message the bridge receives, so a session's Monitor tool wakes per message.

Usage: slack_listen.py [--channel CHANNEL_ID] [--since TS]
Without --channel every channel is included. Without --since it starts from now (no replay of old messages).
"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request

LOCAL_PORT = int(os.environ.get("BRIDGE_LOCAL_PORT", "8788"))
WAIT_SECONDS = 50

argument_parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
argument_parser.add_argument("--channel", default="", help="Slack channel ID; omit for every channel")
argument_parser.add_argument("--since", default=None, help="Slack ts to start after; default is now")
arguments = argument_parser.parse_args()

since_timestamp = arguments.since or f"{time.time():.6f}"
retry_delay_seconds = 1
failures_since_last_error_line = 0
while True:
    query = {"since": since_timestamp, "timeout": WAIT_SECONDS}
    if arguments.channel:
        query["channel"] = arguments.channel
    url = f"http://127.0.0.1:{LOCAL_PORT}/slack/wait?" + urllib.parse.urlencode(query)
    try:
        with urllib.request.urlopen(url, timeout=WAIT_SECONDS + 10) as response:
            result = json.load(response)
    except Exception as error:
        # Server down or restarting: back off up to a minute, and print an error line only now and then.
        if failures_since_last_error_line % 10 == 0:
            print(json.dumps({"listener_error": str(error), "retrying_in_seconds": retry_delay_seconds}), flush=True)
        failures_since_last_error_line += 1
        time.sleep(retry_delay_seconds)
        retry_delay_seconds = min(retry_delay_seconds * 2, 60)
        continue
    retry_delay_seconds, failures_since_last_error_line = 1, 0
    for message in result["messages"]:
        print(json.dumps(message), flush=True)
    since_timestamp = result["latest_ts"]
