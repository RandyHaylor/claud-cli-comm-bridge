#!/usr/bin/env python3
"""Tiny GET-only message bridge between outside agents and Claude CLI sessions on this host.

Public port (exposed through a tunnel), every request needs ?token=:
  GET /send?token=T&msg=TEXT[&to=SESSION_NAME_OR_SHORT_ID][&wait=SECONDS]
      Without to=, the message goes to the middleman Claude session itself, which answers it.
      to= takes a session name or short_id from /sessions. A name shared by several running
      sessions is refused as ambiguous; use the short_id instead.
      Queues a message for a host session and returns at once with its id and a poll URL.
      Optional wait=SECONDS (max 55) holds the request open for an inline reply.
      to=echo replies immediately with "pong: TEXT" (tests the path without any middleman).
  GET /sessions?token=T
      Lists the running Claude sessions on this host (name, short_id, status, kind, start time),
      read straight from disk with no agent involved.
  GET /launch?token=T&name=SESSION_NAME
      Opens a new terminal on the host running Claude Code named SESSION_NAME, in a new folder
      ~/remote-sessions/<chat id>/. Once it shows in /sessions it can be messaged with to=.
  GET /fork?token=T&from=SESSION_NAME_OR_SHORT_ID&name=NEW_SESSION_NAME
      Opens a new terminal in the source session's folder running
      claude --resume <source session id> --fork-session --name NEW_SESSION_NAME.
  GET /reply?token=T&id=MESSAGE_ID
      Returns the reply for a message, or status "waiting".

Local-only port (bound to 127.0.0.1, never tunneled), used by the middleman Claude session:
  GET /pending                       messages not yet handed to a session
  GET /respond?id=MESSAGE_ID&text=T  records the reply for a message
"""
import glob
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PUBLIC_PORT = int(os.environ.get("BRIDGE_PUBLIC_PORT", "8787"))
LOCAL_PORT = int(os.environ.get("BRIDGE_LOCAL_PORT", "8788"))
MIDDLEMAN_SESSION_NAME = os.environ.get("BRIDGE_MIDDLEMAN_SESSION_NAME", "bridge-middleman")
POLL_INTERVAL_SECONDS = int(os.environ.get("BRIDGE_POLL_INTERVAL_SECONDS", "15"))
ACCESS_TOKEN = os.environ.get("BRIDGE_TOKEN") or secrets.token_urlsafe(16)

messages = {}  # message id -> {"to", "msg", "created", "handed_out", "reply"}
messages_lock = threading.Condition()
launched_session_names = set()  # names started through /launch or /fork since this server started


LAUNCH_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "new_remote_session.sh")
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
            "session_id": entry.get("sessionId", ""),
            "cwd": entry.get("cwd", ""),
            "status": entry.get("status"),
            "kind": entry.get("kind"),
            "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("startedAt", 0) / 1000)),
        })
    return sorted(sessions, key=lambda session: session["name"])


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


class PublicHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/robots.txt":
            data = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if url.path == "/":
            return write_json(self, 200, {"service": "claude cli comm bridge", "usage": __doc__})
        if not secrets.compare_digest(query.get("token", ""), ACCESS_TOKEN):
            return write_json(self, 403, {"error": "missing or wrong token"})
        if url.path == "/send":
            return self.handle_send(query)
        if url.path == "/reply":
            return self.handle_reply(query)
        if url.path == "/launch":
            return self.handle_launch(query)
        if url.path == "/fork":
            return self.handle_fork(query)
        if url.path == "/sessions":
            return write_json(self, 200, {"default_to": MIDDLEMAN_SESSION_NAME,
                                          "sessions": [public_session_view(session)
                                                       for session in list_running_sessions()]})
        return write_json(self, 404, {"error": "unknown path"})

    def handle_send(self, query):
        to, text = query.get("to", MIDDLEMAN_SESSION_NAME), query.get("msg", "")
        if not text:
            return write_json(self, 400, {"error": "need msg="})
        target = {"name": to}
        if to not in ("echo", MIDDLEMAN_SESSION_NAME):
            session, error = resolve_session(to)
            if error:
                return write_json(self, 409 if "matches" in error else 404, error)
            target = {key: session[key] for key in ("name", "short_id", "session_id", "cwd")}
        message_id = secrets.token_hex(6)
        with messages_lock:
            messages[message_id] = {"to": to, "target": target, "msg": text, "created": time.time(),
                                    "handed_out": False,
                                    "reply": f"pong: {text}" if to == "echo" else None}
            messages_lock.notify_all()
        wait_seconds = min(float(query.get("wait", "0")), 55.0)
        deadline = time.time() + wait_seconds
        with messages_lock:
            while messages[message_id]["reply"] is None and time.time() < deadline:
                messages_lock.wait(timeout=deadline - time.time())
            reply = messages[message_id]["reply"]
        if reply is None:
            host = self.headers.get("Host", "")
            return write_json(self, 202, {
                "id": message_id, "status": "processing",
                "poll": f"https://{host}/reply?token={ACCESS_TOKEN}&id={message_id}",
                "retry_after_seconds": POLL_INTERVAL_SECONDS,
                "note": f"processing - fetch the poll link every {POLL_INTERVAL_SECONDS} seconds until status is replied"})
        return write_json(self, 200, {"id": message_id, "status": "replied", "reply": reply})

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
            ["gnome-terminal", f"--working-directory={source_session['cwd']}", f"--title={session_name}", "--",
             "bash", "-lc", 'claude --resume "$1" --fork-session --name "$2"; exec bash', "_",
             source_session["session_id"], session_name],
            capture_output=True, text=True, timeout=30, env=environment_without_claude_markers())
        if result.returncode != 0:
            return write_json(self, 500, {"error": "fork failed", "detail": result.stderr.strip()})
        return write_json(self, 200, {
            "status": "forked", "name": session_name, "from": public_session_view(source_session),
            "note": "the fork is written to disk only after its first input"})

    def handle_reply(self, query):
        with messages_lock:
            message = messages.get(query.get("id", ""))
        if not message:
            return write_json(self, 404, {"error": "unknown id"})
        if message["reply"] is None:
            return write_json(self, 202, {
                "status": "processing", "retry_after_seconds": POLL_INTERVAL_SECONDS,
                "note": f"not answered yet - fetch this same link again in {POLL_INTERVAL_SECONDS} seconds"})
        return write_json(self, 200, {"status": "replied", "reply": message["reply"]})


class LocalMiddlemanHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/pending":
            with messages_lock:
                pending = [{"id": message_id, "to": message["target"], "msg": message["msg"]}
                           for message_id, message in messages.items()
                           if message["reply"] is None and not message["handed_out"]]
                for item in pending:
                    messages[item["id"]]["handed_out"] = True
            return write_json(self, 200, {"pending": pending})
        if url.path == "/respond":
            with messages_lock:
                message = messages.get(query.get("id", ""))
                if not message:
                    return write_json(self, 404, {"error": "unknown id"})
                message["reply"] = query.get("text", "")
                messages_lock.notify_all()
            return write_json(self, 200, {"ok": True})
        return write_json(self, 404, {"error": "unknown path"})


if __name__ == "__main__":
    local_server = ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), LocalMiddlemanHandler)
    threading.Thread(target=local_server.serve_forever, daemon=True).start()
    print(f"token: {ACCESS_TOKEN}", flush=True)
    print(f"public port {PUBLIC_PORT}, local middleman port {LOCAL_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PUBLIC_PORT), PublicHandler).serve_forever()
