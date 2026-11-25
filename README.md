# claud-cli-comm-bridge

Slack as the remote interface to Claude Code CLI sessions running on a host machine. Each session gets its own Slack channel; you post there and the session hears it instantly, acts, and replies in the channel.

**Two parts:**
- **Agents (any session):** run `/slack-subscribe` and the session listens to its own channel by itself. Talking to an agent never goes through anything else.
- **Command channel (`#claude-bridge`), handled by the server itself, no agent needed:** the bridge server runs a fixed set of commands posted there (list, launch and fork sessions, type into them) and posts the result back. It handles only those commands; nothing else is relayed to any agent.

It works from a phone, including Claude voice chat with the claude.ai Slack connector: talk to your phone Claude, it posts in Slack, the host session answers.

This is a prototype. Plain Python standard library, no dependencies.

## Use a dedicated Slack workspace

Create a new free Slack workspace just for this. You get free rein over channels (every agent creates its own), no admin approval for the app, and nothing else mixed into the channels your agents read as instructions. The free plan has no canvases; that's fine, documents are shared as uploaded `.md` files.

## Architecture

```
 phone / browser / Claude with Slack connector
                 |
                 v
          Slack workspace  <-------------------------------+
                 |  Events API (HTTPS POST, signed)        |
                 v                                         |
   Tailscale Funnel (public HTTPS)                         |
                 |                                         |
                 v                                         |
 bridge_server.py  public port:  POST /slack/events        |
                   local port (127.0.0.1):                 |
                     /slack/messages  /slack/wait          |
                     /sessions /launch /fork /keys         |
                 ^                    |                    |
   slack_listen.py (under Monitor)    | tmux -L claude-bridge
                 |                    v                    |
       Claude Code sessions  <--  bridge-launched sessions |
                 |   (gnome-terminal windows)              |
                 +--- claude.ai Slack connector (MCP) -----+
                      replies, uploads, channel creation
```

- Slack pushes every message in channels the bot is in to `POST /slack/events`. The server verifies Slack's signature and keeps the last 1000 messages in memory.
- Messages in the command channel are also parsed as commands. The server answers Slack's request at once, runs the command, and posts the result with `chat.postMessage` using the bot token. Its own posts are bot messages, which the hub drops, so they never loop.
- Each session runs `slack_listen.py --channel <id>` under its Monitor tool and is woken per message.
- Sessions post through the claude.ai Slack connector, so all posts appear as the workspace owner. Agents start every post with a tag `[name · short id · folder]`, and the hub drops messages starting with `[`, so agents never hear their own replies.

## Requirements

- Linux with gnome-terminal and tmux
- Python 3
- Claude Code, with the claude.ai Slack connector
- Tailscale (or another HTTPS tunnel that Slack can reach)

## Setup

### a. Create the workspace

At slack.com, create a new workspace (free plan).

### b. Public HTTPS with Tailscale Funnel

```
sudo tailscale up
```

Enable Funnel for your tailnet in the Tailscale admin console (the CLI prints a link if it isn't enabled). Let your user run tailscale without sudo, then expose the bridge's public port (default 8787):

```
sudo tailscale set --operator=$USER
tailscale funnel --bg 8787
```

Your public URL is `https://<machine>.<tailnet>.ts.net`.

### c. Create the Slack app from the manifest

At api.slack.com/apps: Create New App -> From a manifest, pick your workspace, and paste `slack_app_manifest.yaml` with `YOUR-HOST` replaced by your Funnel host. Install the app to the workspace.

Gotcha: the "From scratch" wizard may turn Socket Mode on. Socket Mode must be OFF (Settings -> Socket Mode), or events never reach the Request URL.

### d. Signing secret

Copy the Signing Secret from the app's Basic Information page. Write it without putting it on the command line or in shell history: the `read -s` prompt hides what you paste.

```
mkdir -p ~/.config/claude-bridge
read -s -p "Signing secret: " secret && printf 'SLACK_SIGNING_SECRET=%s\n' "$secret" > ~/.config/claude-bridge/slack.env; unset secret
chmod 600 ~/.config/claude-bridge/slack.env
```

The server reads it on every request (no restart needed). Without it, every event is refused.

### d2. Bot token (for command channel replies)

The manifest includes the bot scope `chat:write`, which lets the server post replies. If your app was created before that scope was added, add `chat:write` under OAuth & Permissions -> Bot Token Scopes, then reinstall the app to the workspace (Slack prompts for it).

On OAuth & Permissions, copy the Bot User OAuth Token (starts with `xoxb-`). Add it to the same private file, again without putting it on the command line, in chat, or in the repo:

```
read -s -p "Bot token: " token && printf 'SLACK_BOT_TOKEN=%s\n' "$token" >> ~/.config/claude-bridge/slack.env; unset token
```

Without the token, commands still run but their replies are not posted (the server logs an error).

### e. Start the server

Recommended: run it as a systemd user service (next section). Manual alternative, from a normal terminal (not inside a Claude Code session): `BRIDGE_PUBLIC_PORT=8787 BRIDGE_LOCAL_PORT=8788 python3 bridge_server.py`

Both port variables are optional (defaults 8787 and 8788). The public port is the one Funnel exposes.

#### Run as a systemd user service

Why: the server keeps running independently of any Claude Code session. Started from inside a session, it dies with that session, and Claude Code also kills idle sessions' background commands when memory runs low.

Install:

```
mkdir -p ~/.config/systemd/user
cp systemd/claude-bridge.service.example ~/.config/systemd/user/claude-bridge.service
# edit it: replace /path/to/claud-cli-comm-bridge, YOUR_USER, UID (id -u) and the DISPLAY value (echo $DISPLAY)
systemctl --user daemon-reload
systemctl --user enable --now claude-bridge
```

Manage:

```
systemctl --user status claude-bridge
systemctl --user restart claude-bridge
journalctl --user -u claude-bridge -f
```

- The `DISPLAY`, `XAUTHORITY` and `DBUS_SESSION_BUS_ADDRESS` lines are needed for `/launch` and `/fork` to open terminal windows, and must match your desktop session.
- A user service runs while you are logged in.

### f. Verify the Request URL

In the app's Event Subscriptions page, the Request URL `https://YOUR-HOST/slack/events` must show Verified. If it doesn't, check the server is running, Funnel is on, and the secret file is right, then click Retry.

### g. Command channel and bot id

1. Create the channel `#claude-bridge` and type `/invite @claude-bridge` in it. Slack only sends a channel's events once the bot is a member.
2. Save the bot's member id (starts with `U`). Get it by listing the channel's members through the Slack connector, or from the bot's profile -> Copy member ID:

   ```
   echo U0XXXXXXXXX > ~/.config/claude-bridge/slack_bot_user_id
   ```

3. Tell the server which channel is the command channel by saving its channel id (starts with `C`). Find it in Slack under the channel's details, at the bottom of the About tab, or by searching for the channel through the Slack connector:

   ```
   echo C0XXXXXXXXX > ~/.config/claude-bridge/command_channel_id
   ```

   (or set `BRIDGE_COMMAND_CHANNEL_ID` in the service environment). Without it, command handling is off; events are still stored. The server reads it on every event, so no restart is needed.

4. Optional, if you changed the local port: `echo 8788 > ~/.config/claude-bridge/local_port`. The skills read it.

### h. Install the skill

```
ln -s "$PWD/skills/slack-subscribe" ~/.claude/skills/slack-subscribe
```

### i. Sign sessions into the Slack connector

In each Claude Code session that should use Slack, run `/mcp` and sign in to the claude.ai Slack connector.

## Usage

- **Command channel:** post commands in `#claude-bridge`; the server itself runs them and replies. No Claude session is involved.
- **Subscribe a session:** run `/slack-subscribe` in it. It creates (or reuses) its own channel `<name>-<short id>` with the bot invited, and listens there.
  - **From your phone or the web:** a session with Remote Control turned on (`/remote-control`, or started with `claude --remote-control`) shows up in the Claude mobile app and on claude.ai under Code. Open it there and type `/slack-subscribe`. No need to be at the host machine, and it works for sessions the bridge didn't launch.
- **Talk to an agent:** post in its channel.

### Commands in #claude-bridge

| Command | What it does |
|---|---|
| `sessions` | Lists the running sessions. |
| `launch NAME` | Starts a new session named NAME in `~/remote-sessions/<chat id>/`, in a visible terminal. |
| `fork FROM NAME` | Forks session FROM (name or short id) into a new session NAME, in FROM's folder. |
| `keys TO text…` | Types the text into session TO and presses Enter (e.g. `keys my-session /compact`). Only for sessions started by launch or fork. |
| `subscribe NAME` | Types `/slack-subscribe` into session NAME. Only for sessions started by launch or fork; otherwise type `/slack-subscribe` in that session yourself. |
| `compact NAME` | Types `/compact` into session NAME. Only for sessions started by launch or fork. |
| `help` | Lists these commands. |

Commands are matched on the first word, case-insensitive. Anything else gets the help text back. Every reply ends with `STATUS: DONE`. The server handles only these commands; to talk to an agent, post in that agent's own channel.

### Conventions

- Every agent post starts with its tag: `[name · short id · folder]`.
- Agents acknowledge first (one line saying what they're about to do), then act.
- Questions come in an uploaded `questions<N>.md` file, numbered, with lettered options. Answer in the main channel without repeating the questions: `questions3.md response: 1a, 2b. 3c: "free text"`.
- The upload comment for a questions file includes the file ID and each question as one short line with its options, so a reader can answer without opening the file.
- Long documents come as uploaded `.md` files.
- No threads: everything is in the main channel.
- Every agent message ends with a status line: `STATUS: WORKING` (more coming), `STATUS: DONE` (finished), or `STATUS: WAITING FOR USER` (needs an answer).
- Replies are short, front-loaded (most important sentence first) and written as plain sentences that sound right read aloud by a voice assistant.

### Tips for voice/phone assistants

- Read #readme first.
- Find the agent's channel by searching for its name.
- Post in the main channel, never in a thread.
- Read replies with `oldest` set to your own message's ts.
- Stop polling when the latest message ends with `STATUS: DONE` or `STATUS: WAITING FOR USER`.
- Answer a questions file as `questionsN.md response: 1a, 2b. 3: "free text"`.

## Helper scripts

`scripts/` holds small bash wrappers for the service and the local endpoints. They read the local port from `~/.config/claude-bridge/local_port` (default 8788).

Install: `scripts/install.sh [TARGET_FOLDER]` makes them executable and symlinks them into TARGET_FOLDER (default `~/claude-cli-comms-bridge-scripts`). Pick a folder of your choice, or one on your PATH. Or copy them by hand and `chmod +x` them.

| Script | What it does |
|---|---|
| `status.sh` | Service status and `tailscale funnel status`. |
| `start.sh` / `stop.sh` / `restart.sh` | Start, stop or restart the service. |
| `logs.sh` | Follow the service log. |
| `sessions.sh` | Table of running sessions. |
| `launch.sh NAME` | Launch a new session. |
| `fork.sh FROM NEW_NAME` | Fork a session. |
| `keys.sh TO TEXT...` | Type text and Enter into a bridge-launched session. |
| `subscribe.sh NAME` | Type `/slack-subscribe` into a session. |
| `compact.sh NAME` | Type `/compact` into a session. |
| `recent-slack.sh [CHANNEL_ID]` | Stored Slack messages, all channels if none given. |

## Suggested channel content

### #readme

```
This workspace is the remote interface to Claude Code sessions on a host machine. Humans and AI agents (for example a phone Claude with the Slack connector) are welcome.

- Each agent has its own channel named <session name>-<short id>. Post there to talk to it; it replies in the same channel.
- Agent posts start with a tag: [name · short id · folder]. Your own messages must NOT start with "[" or the agents never see them.
- Agents acknowledge first, then act.
- Questions arrive as questions<N>.md files. Answer in the main channel: questions3.md response: 1a, 2b. 3c: "free text"
- Long documents arrive as .md files.
- Never use threads; agents only read the main channel.
- To list, start or control sessions, use #claude-bridge. See #command-list.
```

### #command-list

```
Commands for #claude-bridge (post one per message):
sessions              list running sessions
launch NAME           start a new session named NAME
fork FROM NAME        fork session FROM into a new session NAME
keys TO text...       type text into session TO and press Enter (e.g. keys my-session /compact); bridge-launched sessions only
subscribe NAME        make session NAME subscribe to its own channel; bridge-launched sessions only
compact NAME          type /compact into session NAME; bridge-launched sessions only
help                  list these commands
The bridge server answers these itself; anything else gets the help text. To talk to an agent, post in its own channel.
```

### Suggested claude.ai personal preference

```
To talk to my Claude Code agents, use Slack: read #readme first and follow it.
```

## Local endpoints

Bound to 127.0.0.1, no token, never tunneled.

| Endpoint | What it does |
|---|---|
| `GET /slack/messages[?channel=ID][&since=TS]` | Stored messages newer than Slack ts `since`. |
| `GET /slack/wait[?channel=ID][&since=TS][&timeout=SECONDS]` | Same, but blocks (max 50 s) until one arrives. Returns `messages` and `latest_ts` for the next `since`. |
| `GET /sessions` | Running sessions: `name`, `short_id`, `status`, `kind`, `started`. |
| `GET /launch?name=NAME` | New session in `~/remote-sessions/<chat id>/` inside `tmux -L claude-bridge`, with a gnome-terminal attached. Names: 1-64 letters, digits, dot, dash, underscore; refused if already running or launched. |
| `GET /fork?from=NAME_OR_SHORT_ID&name=NEW_NAME` | `claude --resume <id> --fork-session` in the source's folder. Refused until the source has a saved conversation (after its first input). |
| `GET /keys?to=NAME_OR_SHORT_ID&text=TEXT` | Types TEXT and Enter into a bridge-launched session; any other session is refused. |

`slack_listen.py [--channel ID] [--since TS]` prints one JSON line per new message from `/slack/wait`, and keeps retrying while the server is down. Set `BRIDGE_LOCAL_PORT` if the local port isn't 8788.

The public port serves only `POST /slack/events`; everything else is 404.

## Security

- The Slack signature check is what stops anyone on the internet from injecting instructions: without the signing secret, a request to `/slack/events` is refused. Keep `~/.config/claude-bridge/slack.env` private (`chmod 600`), never commit it, and rotate the secret in the Slack app if it leaks.
- Every message in a channel the bot is in is treated by the agents as your instruction. Keep the workspace to yourself.
- Launched and forked sessions run with your user's permissions on the host.

## Lessons learned

- The claude.ai Slack connector can only read and post, not wait for messages, so Slack events plus a local listener are needed for instant pings.
- Web chat fetch tools only open URLs that already appeared in the conversation, so a URL-polling design doesn't work for web Claude.
- Cloudflare quick tunnels serve a managed robots.txt that blocks AI fetchers.
- ngrok free shows an interstitial page that fetchers can't get past.
- Socket Mode must be off, or events never reach the Request URL.
- The bot must be a member of a channel to receive its events.
- Sessions launched from inside a Claude session inherit `CLAUDE_CODE_CHILD_SESSION` and don't register in `~/.claude/sessions` unless the environment is stripped (the launch scripts strip `CLAUDE*` and `AI_AGENT`, keeping `CLAUDE_CODE_TMPDIR`).
- `/compact` sent as a peer message arrives as plain text; built-in commands only run when typed into the prompt, which is what tmux send-keys (`keys`) does.
