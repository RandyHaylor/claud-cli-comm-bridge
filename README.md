# claud-cli-comm-bridge

A tiny GET-only HTTP bridge that lets any outside system or agent, including web ChatGPT or Claude that can only fetch URLs, list, launch, fork and message Claude Code CLI sessions running on a host.

This is an experiment / prototype. Plain Python standard library, no dependencies.

Requires Linux with gnome-terminal for `/launch` and `/fork` (they open new gnome-terminal windows).

## How it works

- `bridge_server.py` runs two ports:
  - a public port, exposed to the internet through a tunnel; every request needs `?token=`
  - a local-only port (127.0.0.1) for the middleman
- The list of running sessions is read straight from Claude Code's registry files in `~/.claude/sessions/`.
- Messages are relayed by a **middleman**: a normal Claude Code session on the host that runs `watch_pending.py` (prints one JSON line per queued message) and passes each message to its target session with its SendMessage tool. It then posts the reply back with `/respond`.
- Sessions don't reply to peer messages on their own, so the middleman must explicitly ask the target session to reply.
- Messages sent without `to=` go to the middleman itself, which answers them.

## Quick start

1. From a normal terminal (not from inside Claude Code), start the server:

   ```
   BRIDGE_TOKEN=pick-a-long-secret python3 bridge_server.py
   ```

   Defaults: public port 8787, local port 8788. Override with `BRIDGE_PUBLIC_PORT` / `BRIDGE_LOCAL_PORT`. Without `BRIDGE_TOKEN` a random token is generated and printed.

2. Start a tunnel to the public port. What worked:

   ```
   ssh -R 80:127.0.0.1:8787 nokey@localhost.run
   ```

3. Open a Claude Code session in this folder and ask it to be the middleman: monitor `python3 watch_pending.py`, deliver each message to its target session with SendMessage (asking the target to reply), and post the reply to `http://127.0.0.1:8788/respond?id=ID&text=REPLY`. Name the session `bridge-middleman`, or set `BRIDGE_MIDDLEMAN_SESSION_NAME` to its name.

4. Give the outside agent the tunnel URL and token, e.g. `https://<tunnel host>/sessions?token=...`.

## Endpoints

Public port (all except `/` and `/robots.txt` need `token=`):

| Endpoint | What it does |
|---|---|
| `/robots.txt` | Allows all fetchers. |
| `/` | Usage text. |
| `/sessions?token=T` | Running sessions: `name`, `short_id` (first 8 chars of the session id), `status`, `kind`, `started`. |
| `/send?token=T&msg=TEXT[&to=NAME_OR_SHORT_ID][&wait=SECONDS]` | Queues a message. Returns at once with status `processing` and a poll link; `wait=` (max 55) holds the request open for an inline reply. `to=echo` answers `pong: TEXT` immediately. A name shared by several running sessions is refused as ambiguous, listing the matches with their short ids. An unknown target is refused. |
| `/reply?token=T&id=ID` | The reply, or status `processing`. |
| `/launch?token=T&name=NAME` | Opens a new gnome-terminal running `claude --name NAME` in a new folder `~/remote-sessions/<chat id>/`. Refuses a name already used by a running session or launched since the server started. |
| `/fork?token=T&from=NAME_OR_SHORT_ID&name=NEW_NAME` | Opens a new gnome-terminal in the source session's folder running `claude --resume <source session id> --fork-session --name NEW_NAME`. Same name rules as `/launch`. Refused if the source has no saved conversation yet. |

Local port (127.0.0.1 only, for the middleman):

| Endpoint | What it does |
|---|---|
| `/pending` | Messages not yet handed out. Each carries the target's `name`, `short_id`, `session_id` and `cwd`, so the middleman can pick the right session when names are shared. |
| `/respond?id=ID&text=REPLY` | Records the reply. |

Names for `/launch` and `/fork`: 1-64 letters, digits, dot, dash or underscore.

## Notes

- Launched and forked sessions get a cleaned environment: every variable starting with `CLAUDE` and `AI_AGENT` is removed, so a server started from inside a Claude Code session doesn't mark new windows as child sessions (which turns off transcript saving and keeps them out of `~/.claude/sessions`). `CLAUDE_CODE_TMPDIR` is kept on purpose: on hosts where the default temp folder is unusable, Claude Code refuses to start without it.
- A session only saves its conversation after its first input. Until then it can't be forked (`/fork` says so).
- A `--fork-session` fork is likewise not written to disk until its first input.

## Lessons learned

- Cloudflare quick tunnels serve a managed robots.txt that blocks Claude-User and ChatGPT-User.
- ngrok free shows a browser-warning interstitial that web fetchers can't get past.
- localhost.run works, but rotates its domain and exposes the host IP in an `x-backend-addr` header.
- Web fetch tools time out on long-held requests, so `/send` returns `processing` plus a poll link immediately.

## Security warning

Anyone with the URL and token can message sessions and launch or fork Claude Code sessions on your host. Tokens travel in URLs, so they end up in logs and chat histories. Use a long random token, stop the server and tunnel when you're done, and don't run this on a machine you can't afford to expose.
