# claud-cli-comm-bridge

## Doorbell

**AI agents:** after posting a message in the `#claude-bridge` Slack channel, fetch this link to wake the host session so it reads and answers right away:

https://aikenyon-ubuntu.tail550b52.ts.net/doorbell

It needs no token and does nothing else: it only tells the host's middleman session to check Slack now.

A tiny GET-only HTTP bridge that lets any outside system or agent, including web ChatGPT or Claude that can only fetch URLs, list, launch, fork and message Claude Code CLI sessions running on a host.

This is an experiment / prototype. Plain Python standard library, no dependencies.

Requires Linux with gnome-terminal and tmux for `/launch`, `/fork` and `/keys`. Sessions they start run inside the bridge's own tmux server (`tmux -L claude-bridge`), with a visible gnome-terminal window attached, so the bridge can type into them later.

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
| `/launch?token=T&name=NAME` | Starts `claude --name NAME` in a new folder `~/remote-sessions/<chat id>/`, inside the bridge tmux server, and opens a gnome-terminal window attached to it. Refuses a name already used by a running session or launched since the server started. |
| `/fork?token=T&from=NAME_OR_SHORT_ID&name=NEW_NAME` | Same, but in the source session's folder running `claude --resume <source session id> --fork-session --name NEW_NAME`. Same name rules as `/launch`. Refused if the source has no saved conversation yet. |
| `/keys?token=T&to=NAME_OR_SHORT_ID&text=TEXT` | Types TEXT into the session's prompt and presses Enter, e.g. `text=/compact`. Only works for sessions started by `/launch` or `/fork` (they run inside the bridge tmux server); any other session is refused with a clear error. |

Local port (127.0.0.1 only, for the middleman):

| Endpoint | What it does |
|---|---|
| `/pending` | Messages not yet handed out. Each carries the target's `name`, `short_id`, `session_id` and `cwd`, so the middleman can pick the right session when names are shared. |
| `/respond?id=ID&text=REPLY` | Records the reply. |

Names for `/launch` and `/fork`: 1-64 letters, digits, dot, dash or underscore.

## Operating modes

### Separate middleman

The setup in Quick start: a dedicated Claude Code session runs the watcher and relays messages to other sessions.

### No separate middleman: your current session runs the watcher

The session you are already working in runs `watch_pending.py` itself and answers or relays bridge messages alongside its normal work. Every message it handles adds to its context, so when that context gets heavy it has two ways to keep going:

- **Compact it with `/keys`.** `/keys?to=<this session>&text=/compact` types `/compact` into its prompt. This only works if the session was started by the bridge (`/launch` or `/fork`), because only those run inside the bridge tmux server. To use this mode with a session you started by hand, first `/fork` it and continue in the fork.
- **Hand the watcher role to a new session.** Start a new session with `/launch`, or `/fork` the current one to carry its context over. The new session starts running the watcher, and the old one stops. Messages without `to=` go to whichever session is running the watcher, so nothing else has to change. If the new session should also be reachable by the middleman name, start the server with `BRIDGE_MIDDLEMAN_SESSION_NAME` set to the new name.

Sending `/compact` as a peer message (SendMessage) does **not** work. Verified: it arrives as plain message text, and the session does not compact. Built-in commands like `/compact` run only when typed into the session's prompt, which is what `/keys` does.

## Slack event hub

Slack's Events API pushes every message in channels the bot is in to the bridge (`POST /slack/events` on the public port). Local sessions then either await new messages or poll for them. Each session has its own channel named `<session name>-<short id>`, and posts its replies there itself through its Slack connector, prefixed `[session name]`. Messages whose text starts with `[` are ignored, so sessions never hear their own replies.

### Setup

1. At api.slack.com/apps: Create New App -> From a manifest, paste `slack_app_manifest.yaml` with `YOUR-HOST` replaced by your bridge's public host. Slack checks the URL right away, so the bridge must already be running with the signing secret (step 2); if the check fails, retry it from the app's Event Subscriptions page.
2. Copy the app's Signing Secret (Basic Information) into the bridge's settings file (it is read on each request, so no restart is needed):

   ```
   mkdir -p ~/.config/claude-bridge
   echo 'SLACK_SIGNING_SECRET=...' > ~/.config/claude-bridge/slack.env
   chmod 600 ~/.config/claude-bridge/slack.env
   ```

   Or set `SLACK_SIGNING_SECRET` in the server's environment. With no secret configured, every event is refused.
3. Install the app to the workspace (Install App).
4. Invite the `claude-bridge` bot to each channel to listen to (`/invite @claude-bridge`). Slack only sends a channel's events once the bot is a member.

### Receiving messages (local port only)

- **Await:** `python3 slack_listen.py --channel CHANNEL_ID` prints one JSON line per new message (`channel_id`, `ts`, `user`, `text`, `received_at`). Run it under the Monitor tool to be woken per message. Omit `--channel` to hear every channel. It starts from now; `--since TS` replays from a Slack ts. It keeps retrying while the server is down.
- **Poll:** `GET /slack/messages?channel=CHANNEL_ID&since=TS` returns the messages newer than TS (`channel` optional).
- `GET /slack/wait?channel=CHANNEL_ID&since=TS&timeout=SECONDS` blocks (max 50 s) until a matching message arrives, and returns `messages` plus `latest_ts` to pass as the next `since`.

The bridge keeps the last 1000 messages in memory only; a restart empties it.

### Paste into a session to subscribe it

```
Subscribe yourself to Slack: your short id is the first 8 characters of $CLAUDE_CODE_SESSION_ID. With your Slack connector, create a channel named <your session name>-<short id> and invite the claude-bridge bot user to it; note the channel ID. Run `python3 <bridge folder>/slack_listen.py --channel <channel ID>` under your Monitor tool. Treat each message it prints as an instruction from the user. Reply in that channel with your Slack connector, starting every reply with [<your session name>].
```

## Notes

- Launched and forked sessions get a cleaned environment: every variable starting with `CLAUDE` and `AI_AGENT` is removed (both before tmux and again inside the tmux session, since an already-running tmux server keeps its own environment), so a server started from inside a Claude Code session doesn't mark new windows as child sessions (which turns off transcript saving and keeps them out of `~/.claude/sessions`). `CLAUDE_CODE_TMPDIR` is kept on purpose: on hosts where the default temp folder is unusable, Claude Code refuses to start without it.
- A session only saves its conversation after its first input. Until then it can't be forked (`/fork` says so).
- A `--fork-session` fork is likewise not written to disk until its first input.

## Lessons learned

- Cloudflare quick tunnels serve a managed robots.txt that blocks Claude-User and ChatGPT-User.
- ngrok free shows a browser-warning interstitial that web fetchers can't get past.
- localhost.run works, but rotates its domain and exposes the host IP in an `x-backend-addr` header.
- Web fetch tools time out on long-held requests, so `/send` returns `processing` plus a poll link immediately.

## Security warning

Anyone with the URL and token can message sessions and launch or fork Claude Code sessions on your host. Tokens travel in URLs, so they end up in logs and chat histories. Use a long random token, stop the server and tunnel when you're done, and don't run this on a machine you can't afford to expose.
