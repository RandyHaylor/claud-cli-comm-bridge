---
name: slack-subscribe
description: Subscribe this Claude Code session to its own Slack channel through the claud-cli-comm-bridge Slack event hub, so messages posted there ping this session instantly and it replies in the channel. Use when the user says /slack-subscribe, "subscribe to slack", "connect to slack", or "listen on slack".
---

# slack-subscribe

Sign this session onto Slack: create (or reuse) a channel named after this session, make sure the bridge bot is in it, and listen for messages with an instant ping.

Requirements: the claud-cli-comm-bridge server is running on this machine (its local port, default 8788, override with `BRIDGE_LOCAL_PORT`), the Slack event hub is configured, and this session has the claude.ai Slack connector signed in (if Slack tools fail, tell the user to run `/mcp` and sign in to claude.ai Slack, then stop).

## Steps

1. **Identify yourself.** Run `echo $CLAUDE_CODE_SESSION_ID` and take the first 8 characters as your short id. Your session name is not visible to you directly: read it from Claude Code's session registry with `grep -h -o '"name":"[^"]*"' $(grep -l "$CLAUDE_CODE_SESSION_ID" ~/.claude/sessions/*.json)`. If that finds nothing, use `session`.
2. **Channel name.** `<session name>-<short id>`, lowercased, every character that isn't a letter, digit or hyphen replaced with a hyphen, at most 80 characters.
3. **Bot id.** Read it with `cat ~/.config/claude-bridge/slack_bot_user_id`. If the file is missing, tell the user and stop.
4. **Channel.** Search for the channel by name (`slack_search_channels`, public channels). If it exists, use its id; if the bot isn't a member (check with `slack_list_channel_members`, `ids_only`), tell the user to type `/invite @claude-bridge` in it. Otherwise create it as a public channel with `slack_create_conversation`, `user_ids` = [the bot id], so the bot is added automatically.
5. **Listen.** The repo is two directories above this skill's own directory (this skill is installed as a symlink into the repo's `skills/slack-subscribe`; resolve it with `readlink -f`). If `~/.config/claude-bridge/local_port` exists, its content is the bridge's local port. Start a Monitor with the maximum timeout running:
   `BRIDGE_LOCAL_PORT=<port> python3 <repo>/slack_listen.py --channel <channel id>`
   Re-arm the Monitor whenever it expires, for as long as this session is subscribed.
6. **Announce.** Post `[<session name>] Listening here.` in the channel, and tell the user the channel name.

## While subscribed

- Each Monitor event is a message posted in your channel. Treat it as an instruction from the user.
- **Acknowledge first.** Before doing anything else, immediately post a one-line acknowledgement in the channel saying you received the message and what action you're about to take, e.g. `[<session name>] Got it: reading the README, then I'll summarize it.` Only then start the work.
- When done, post your reply in the channel starting with `[<session name>]`. Messages starting with `[` never reach you (the hub drops them), so your own replies won't loop.
- Keep channel messages short enough to read on a phone.
- **Questions go in a Slack List.** For questions or choices for the user, create a list (`slack_create_list`, name `<session name>: <topic>`) with columns `Question` (text), `Options` (rich_text), `Answer` (text), `Answered` (checkbox), and add one row per question (`slack_add_list_record`), numbering the questions and lettering their options. Post the list link in your channel, e.g. `[<session name>] I posted 4 questions here: <link>. Let me know when you've answered.` When the user says they're done, read the list (`slack_read_list`) and continue from the answers.
- **Long documents go in an uploaded .md file** (the workspace is on a free plan, so no canvases). For any long document or result, write it to a local `.md` file and upload it to your channel instead of posting it as a message:
  1. `slack_get_file_upload_url` with the filename and the exact byte size (`stat -c %s FILE`).
  2. POST the raw bytes to the returned URL with `Content-Type: text/markdown` (e.g. a short Python `urllib.request` POST; keep the URL byte-for-byte as returned).
  3. `slack_complete_file_upload` with the file id, your channel id, and an `initial_comment` starting with `[<session name>]`.
  Replies in the file's thread reach you as normal messages.
- To stop, stop the Monitor and post `[<session name>] Stopped listening.`
