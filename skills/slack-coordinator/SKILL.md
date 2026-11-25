---
name: slack-coordinator
description: Make this Claude Code session the coordinator for the claud-cli-comm-bridge Slack command channel (default #claude-bridge), so it hears every message there instantly and runs the commands sessions, launch, fork, keys and subscribe through the bridge's local endpoints. Use when the user says /slack-coordinator, "be the coordinator", or "listen on the command channel".
---

# slack-coordinator

Listen on the Slack command channel and run bridge commands posted there.

Requirements: the claud-cli-comm-bridge server is running on this machine, and this session has the claude.ai Slack connector signed in (if Slack tools fail, tell the user to run `/mcp` and sign in to claude.ai Slack, then stop).

## Steps

1. **Identify yourself and your tag** exactly as in the slack-subscribe skill (steps 1 and 2): every post starts with `[<session name> · <short id> · <location>]`.
2. **Local port.** If `~/.config/claude-bridge/local_port` exists, its content is the bridge's local port; otherwise use `8788`. The local base URL is `http://127.0.0.1:<port>`.
3. **Command channel.** The channel is `claude-bridge` unless the user named another. Find it by name with `slack_search_channels`. If it doesn't exist, tell the user and stop.
4. **Bot membership.** Read the bot id with `cat ~/.config/claude-bridge/slack_bot_user_id` (missing: tell the user and stop). Check it is in the channel with `slack_list_channel_members` (`ids_only`). If not, tell the user to type `/invite @claude-bridge` in the channel, and stop.
5. **Listen.** The repo is two directories above this skill's own directory (resolve the symlink with `readlink -f`). Start a Monitor with the maximum timeout running:
   `BRIDGE_LOCAL_PORT=<port> python3 <repo>/slack_listen.py --channel <channel id>`
   Re-arm the Monitor whenever it expires, for as long as you are the coordinator.
6. **Announce.** Post `<tag> Coordinator listening here.` in the channel.

## Commands

Each Monitor event is a message in the command channel; treat it as an instruction from the user. **Acknowledge first**: post a one-line acknowledgement of what you're about to do, then act. Call the local endpoints with `curl -s`, URL-encoding values (`--get --data-urlencode`).

| Message | Action |
|---|---|
| `sessions` | `GET /sessions`; post a compact table: name, short id, status, started. |
| `launch NAME` | `GET /launch?name=NAME` |
| `fork FROM NAME` | `GET /fork?from=FROM&name=NAME` |
| `keys TO text…` | `GET /keys?to=TO&text=<text…>` |
| `subscribe NAME` | `GET /keys?to=NAME&text=/slack-subscribe`. Works only for sessions started by launch or fork; if refused, tell the user to type `/slack-subscribe` in that session. |

Post each result (or the error the endpoint returned) in one short line. Anything else: answer it directly.

## Conventions

Same as slack-subscribe: every post starts with your tag; always post in the main channel, never in threads; keep messages short and front-loaded (most important sentence first), in plain sentences that sound right read aloud by a voice assistant; end every message with a status line: `STATUS: WORKING`, `STATUS: DONE`, or `STATUS: WAITING FOR USER`; question-file upload comments include the file ID and each question as one short line with its options; questions go in uploaded `questions<N>.md` files answered as `questions3.md response: 1a, 2b. 3c: "text"`; long documents go in uploaded `.md` files (upload steps are in the slack-subscribe skill).

To stop, stop the Monitor and post `<tag> Coordinator stopped.`
