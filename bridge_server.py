#!/usr/bin/env python3
"""Slack event hub and session control for Claude Code CLI sessions on this host.

Public port (exposed through an HTTPS tunnel such as Tailscale Funnel):
  POST /slack/events   Slack Events API receiver, verified by Slack's request signature
                       (SLACK_SIGNING_SECRET from the environment or ~/.config/claude-bridge/slack.env).
                       Stores channel messages, except bot messages and text starting with "[".
  Anything else gets 404.

Local-only port (bound to 127.0.0.1, never tunneled, no token):
  GET /slack/messages[?channel=CHANNEL_ID][&since=TS]                Slack messages newer than TS
  GET /slack/wait[?channel=CHANNEL_ID][&since=TS][&timeout=SECONDS]  same, but blocks (max 50 s) until one arrives
  GET /sessions                                    running Claude sessions (name, short_id, status, kind, started)
  GET /launch?name=SESSION_NAME                    new session in ~/remote-sessions/<chat id>/
  GET /fork?from=SESSION_NAME_OR_SHORT_ID&name=NEW_SESSION_NAME
                                                   claude --resume <source id> --fork-session in the source's folder
  GET /keys?to=SESSION_NAME_OR_SHORT_ID&text=TEXT  types TEXT and Enter into a session started by /launch or /fork
  /launch and /fork start Claude inside the bridge's own tmux server (tmux -L claude-bridge) with a
  visible gnome-terminal attached, so /keys can type into those sessions later.
"""
import glob
import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PUBLIC_PORT = int(os.environ.get("BRIDGE_PUBLIC_PORT", "8787"))
LOCAL_PORT = int(os.environ.get("BRIDGE_LOCAL_PORT", "8788"))
launched_session_names = set()  # names started through /launch or /fork since this server started


LAUNCH_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "new_remote_session.sh")
TMUX_WINDOW_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "open_claude_in_tmux_window.sh")
BRIDGE_TMUX_SERVER = "claude-bridge"  # tmux -L socket name; must match open_claude_in_tmux_window.sh
SESSION_REGISTRY_DIRECTORY = os.path.expanduser("~/.claude/sessions")
PROJECTS_DIRECTORY = os.path.expanduser("~/.claude/projects")


def list_running_sessions():
    """Reads Claude Code's per-session registry files; keeps only sessions whose process is alive."""
    sessions = []
    for file_name in os.listdir(SESSION_REGISTRY_DIRECTORY):
        if not file_name.endswith(".json"):
            continue
        try:
            with open(os.path.join(SESSION_REGISTRY_DIRECTORY, file_name)) as registry_file:
                entry = json.load(registry_file)
            os.kill(int(entry["pid"]), 0)
        except (OSError, ValueError, KeyError):
            continue
        if not entry.get("name"):
            continue
        sessions.append({
            "name": entry["name"],
            "short_id": entry.get("sessionId", "")[:8],
            "pid": int(entry["pid"]),
            "session_id": entry.get("sessionId", ""),
            "cwd": entry.get("cwd", ""),
            "status": entry.get("status"),
            "kind": entry.get("kind"),
            "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("startedAt", 0) / 1000)),
        })
    return sorted(sessions, key=lambda session: session["name"])


def find_bridge_tmux_pane_for_process(process_id):
    """Returns the bridge tmux pane id whose shell is an ancestor of process_id, or None."""
    listing = subprocess.run(["tmux", "-L", BRIDGE_TMUX_SERVER, "list-panes", "-a", "-F", "#{pane_pid} #{pane_id}"],
                             capture_output=True, text=True, timeout=10)
    if listing.returncode != 0:
        return None  # no bridge tmux server running
    pane_id_by_shell_process = dict(line.split() for line in listing.stdout.splitlines() if line.strip())
    current_process = str(process_id)
    while current_process not in ("0", "1"):
        if current_process in pane_id_by_shell_process:
            return pane_id_by_shell_process[current_process]
        try:
            with open(f"/proc/{current_process}/stat") as stat_file:
                # the parent pid is the 2nd field after the parenthesised command name
                current_process = stat_file.read().rsplit(")", 1)[1].split()[1]
        except OSError:
            return None
    return None


def public_session_view(session):
    """The fields safe to show publicly: no cwd, pid or full session id."""
    return {key: session[key] for key in ("name", "short_id", "status", "kind", "started")}


def resolve_session(name_or_short_id):
    """Returns (session, None) or (None, error body) for a running session name or short id."""
    running_sessions = list_running_sessions()
    matches = [session for session in running_sessions if session["name"] == name_or_short_id]
    if not matches:
        matches = [session for session in running_sessions if session["short_id"] == name_or_short_id]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, {"error": f"no such session: {name_or_short_id}"}
    return None, {"error": f"ambiguous: {len(matches)} running sessions match {name_or_short_id}; use a short_id",
                  "matches": [{"name": session["name"], "short_id": session["short_id"]} for session in matches]}


def environment_without_claude_markers():
    """Copy of this process's environment minus CLAUDE* and AI_AGENT, so launched sessions start clean.
    CLAUDE_CODE_TMPDIR is kept: hosts where the default temp folder is unusable depend on it."""
    return {name: value for name, value in os.environ.items()
            if name == "CLAUDE_CODE_TMPDIR" or not (name.startswith("CLAUDE") or name == "AI_AGENT")}


def session_name_problem(session_name):
    """Returns an (http status, error body) pair if the new session name is invalid or taken, else None."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", session_name):
        return 400, {"error": "name= is required: 1-64 letters, digits, dot, dash or underscore"}
    # A fresh session has no registry file until later, so names launched here are remembered too.
    if session_name in launched_session_names or any(
            session["name"] == session_name for session in list_running_sessions()):
        return 409, {"error": f"a session named {session_name} is already running"}
    return None


def write_json(handler, status, body):
    data = json.dumps(body, indent=2).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class PublicSlackEventsHandler(BaseHTTPRequestHandler):
    """Public port: only POST /slack/events. Everything else gets a 404."""
    def do_GET(self):
        return write_json(self, 404, {"error": "unknown path"})

    def do_POST(self):
        if urlparse(self.path).path == "/slack/events":
            return self.handle_slack_event()
        return write_json(self, 404, {"error": "unknown path"})

    def handle_slack_event(self):
        """Slack Events API receiver. Refuses everything unless Slack's signature checks out."""
        raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        signing_secret = read_slack_signing_secret()
        if not signing_secret:
            return write_json(self, 403, {"error": "no Slack signing secret configured; refusing all events"})
        timestamp = self.headers.get("X-Slack-Request-Timestamp", "")
        try:
            timestamp_is_fresh = abs(time.time() - int(timestamp)) <= 300
        except ValueError:
            timestamp_is_fresh = False
        if not timestamp_is_fresh:
            return write_json(self, 403, {"error": "missing or stale timestamp"})
        expected_signature = "v0=" + hmac.new(signing_secret.encode(), b"v0:" + timestamp.encode() + b":" + raw_body,
                                              hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, self.headers.get("X-Slack-Signature", "")):
            return write_json(self, 403, {"error": "bad signature"})
        try:
            payload = json.loads(raw_body)
        except ValueError:
            return write_json(self, 400, {"error": "body is not JSON"})
        if payload.get("type") == "url_verification":
            return write_json(self, 200, {"challenge": payload.get("challenge", "")})
        event = payload.get("event", {})
        if (payload.get("type") == "event_callback" and event.get("type") == "message"
                and not event.get("subtype") and not event.get("bot_id")
                and not event.get("text", "").startswith("[")):
            store_slack_message({"channel_id": event.get("channel", ""), "ts": event.get("ts", "0"),
                                 "user": event.get("user", ""), "text": event.get("text", ""),
                                 "received_at": time.time()})
        return write_json(self, 200, {"ok": True})


SLACK_SETTINGS_FILE_PATH = os.path.expanduser("~/.config/claude-bridge/slack.env")
SLACK_HISTORY_LIMIT = 1000
slack_messages = []  # oldest first: {"channel_id", "ts", "user", "text", "received_at"}
slack_messages_lock = threading.Condition()


def read_slack_signing_secret():
    """SLACK_SIGNING_SECRET from the environment, else from ~/.config/claude-bridge/slack.env, else ''."""
    if os.environ.get("SLACK_SIGNING_SECRET"):
        return os.environ["SLACK_SIGNING_SECRET"]
    try:
        with open(SLACK_SETTINGS_FILE_PATH) as settings_file:
            for line in settings_file:
                name, _, value = line.strip().partition("=")
                if name.strip() == "SLACK_SIGNING_SECRET":
                    return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def slack_timestamp_value(slack_timestamp):
    try:
        return Decimal(slack_timestamp)
    except (InvalidOperation, TypeError):
        return Decimal(0)


def store_slack_message(message):
    """Adds a message unless Slack already delivered it (retries repeat the same channel and ts)."""
    with slack_messages_lock:
        if any(stored["channel_id"] == message["channel_id"] and stored["ts"] == message["ts"]
               for stored in slack_messages):
            return
        slack_messages.append(message)
        del slack_messages[:-SLACK_HISTORY_LIMIT]
        slack_messages_lock.notify_all()


def slack_messages_newer_than(since_timestamp, channel_id):
    """Messages after since_timestamp, in one channel or (channel_id empty) all. Caller holds the lock."""
    since_value = slack_timestamp_value(since_timestamp)
    return [message for message in slack_messages
            if slack_timestamp_value(message["ts"]) > since_value
            and (not channel_id or message["channel_id"] == channel_id)]


def latest_slack_timestamp(found_messages, since_timestamp):
    if not found_messages:
        return since_timestamp
    return max((message["ts"] for message in found_messages), key=slack_timestamp_value)


class LocalControlHandler(BaseHTTPRequestHandler):
    """Local-only port (127.0.0.1, no token): Slack message reads and session control."""
    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/sessions":
            return write_json(self, 200, {"sessions": [public_session_view(session)
                                                       for session in list_running_sessions()]})
        if url.path == "/launch":
            return self.handle_launch(query)
        if url.path == "/fork":
            return self.handle_fork(query)
        if url.path == "/keys":
            return self.handle_keys(query)
        if url.path in ("/slack/messages", "/slack/wait"):
            since_timestamp, channel_id = query.get("since", "0"), query.get("channel", "")
            try:
                wait_seconds = min(max(float(query.get("timeout", "50")), 0.0), 50.0) if url.path == "/slack/wait" else 0
            except ValueError:
                return write_json(self, 400, {"error": "timeout= must be a number of seconds"})
            deadline = time.time() + wait_seconds
            with slack_messages_lock:
                found_messages = slack_messages_newer_than(since_timestamp, channel_id)
                while not found_messages and time.time() < deadline:
                    slack_messages_lock.wait(timeout=deadline - time.time())
                    found_messages = slack_messages_newer_than(since_timestamp, channel_id)
            return write_json(self, 200, {"messages": found_messages,
                                          "latest_ts": latest_slack_timestamp(found_messages, since_timestamp)})
        return write_json(self, 404, {"error": "unknown path"})

    def handle_launch(self, query):
        session_name = query.get("name", "")
        problem = session_name_problem(session_name)
        if problem:
            return write_json(self, *problem)
        launched_session_names.add(session_name)
        result = subprocess.run([LAUNCH_SCRIPT_PATH, session_name], capture_output=True, text=True, timeout=30,
                                env=environment_without_claude_markers())
        if result.returncode != 0:
            return write_json(self, 500, {"error": "launch failed", "detail": result.stderr.strip()})
        launch_output = dict(line.split(": ", 1) for line in result.stdout.strip().splitlines() if ": " in line)
        return write_json(self, 200, {
            "status": "launched", "name": session_name, "chat_id": launch_output.get("chat id"),
            "note": "the session takes a few seconds to start; it appears in /sessions once running"})

    def handle_fork(self, query):
        source_session, error = resolve_session(query.get("from", ""))
        if error:
            return write_json(self, 409 if "matches" in error else 404, error)
        session_name = query.get("name", "")
        problem = session_name_problem(session_name)
        if problem:
            return write_json(self, *problem)
        # Claude Code saves each conversation as ~/.claude/projects/<folder>/<session id>.jsonl,
        # but only after the session's first input; --resume fails without it.
        if not glob.glob(os.path.join(PROJECTS_DIRECTORY, "*", source_session["session_id"] + ".jsonl")):
            return write_json(self, 409, {
                "error": "source session has no saved conversation yet; send it a message first"})
        launched_session_names.add(session_name)
        result = subprocess.run(
            [TMUX_WINDOW_SCRIPT_PATH, session_name, source_session["cwd"],
             "--resume", source_session["session_id"], "--fork-session"],
            capture_output=True, text=True, timeout=30, env=environment_without_claude_markers())
        if result.returncode != 0:
            return write_json(self, 500, {"error": "fork failed", "detail": result.stderr.strip()})
        return write_json(self, 200, {
            "status": "forked", "name": session_name, "from": public_session_view(source_session),
            "note": "the fork is written to disk only after its first input"})

    def handle_keys(self, query):
        session, error = resolve_session(query.get("to", ""))
        if error:
            return write_json(self, 409 if "matches" in error else 404, error)
        text = query.get("text", "")
        if not text:
            return write_json(self, 400, {"error": "need text="})
        tmux_pane = find_bridge_tmux_pane_for_process(session["pid"])
        if not tmux_pane:
            return write_json(self, 409, {
                "error": f"{session['name']} is not running inside a bridge tmux session; "
                         "only sessions started with /launch or /fork can receive keys"})
        # -l types the text literally; Enter is sent separately so it is pressed, not typed.
        for keys_arguments in (["-l", text], ["Enter"]):
            subprocess.run(["tmux", "-L", BRIDGE_TMUX_SERVER, "send-keys", "-t", tmux_pane, *keys_arguments],
                           check=True, timeout=10)
            time.sleep(0.3)
        return write_json(self, 200, {"status": "sent", "to": public_session_view(session), "text": text})


if __name__ == "__main__":
    local_server = ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), LocalControlHandler)
    threading.Thread(target=local_server.serve_forever, daemon=True).start()
    print(f"public port {PUBLIC_PORT} (POST /slack/events only), local port {LOCAL_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PUBLIC_PORT), PublicSlackEventsHandler).serve_forever()
