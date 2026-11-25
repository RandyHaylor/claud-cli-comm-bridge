---
name: slack-subscribe
description: Subscribe this Claude Code session to its own Slack channel through the claud-cli-comm-bridge Slack event hub, so messages posted there ping this session instantly and it replies in the channel. Use when the user says /slack-subscribe, "subscribe to slack", "connect to slack", or "listen on slack".
---

# slack-subscribe

Sign this session onto Slack: create (or reuse) a channel named after this session, make sure the bridge bot is in it, and listen for messages with an instant ping.

The user can trigger this from anywhere for a session with Remote Control on: they open the session in the Claude mobile app or on claude.ai under Code and type `/slack-subscribe`.

Requirements: the claud-cli-comm-bridge server is running on this machine (its local port, default 8788, override with `BRIDGE_LOCAL_PORT`), the Slack event hub is configured, and this session has the claude.ai Slack connector signed in (if Slack tools fail, tell the user to run `/mcp` and sign in to claude.ai Slack, then stop).

## Steps

1. **Identify yourself.** Run `echo $CLAUDE_CODE_SESSION_ID` and take the first 8 characters as your short id. Your session name is not visible to you directly: read it from Claude Code's session registry with `grep -h -o '"name":"[^"]*"' $(grep -l "$CLAUDE_CODE_SESSION_ID" ~/.claude/sessions/*.json)`. If that finds nothing, use `session`. Your location is your working folder (`pwd`, with your home folder written as `~`).
2. **Your tag.** Every message you post in Slack starts with your tag: `[<session name> · <short id> · <location>]`, e.g. `[comm-bridge · e1ff39b6 · ~/projects/comm-bridge]`. All posts appear under the same Slack user, so the tag is how the reader knows which agent wrote it and where it runs.
3. **Channel name.** `<session name>-<short id>`, lowercased, every character that isn't a letter, digit or hyphen replaced with a hyphen, at most 80 characters.
4. **Bot id.** Read it with `cat ~/.config/claude-bridge/slack_bot_user_id`. If the file is missing, tell the user and stop.
5. **Channel.** Search for the channel by name (`slack_search_channels`, public channels). If it exists, use its id; if the bot isn't a member (check with `slack_list_channel_members`, `ids_only`), tell the user to type `/invite @claude-bridge` in it. Otherwise create it as a public channel with `slack_create_conversation`, `user_ids` = [the bot id], so the bot is added automatically.
6. **Listen.** The repo is two directories above this skill's own directory (this skill is installed as a symlink into the repo's `skills/slack-subscribe`; resolve it with `readlink -f`). If `~/.config/claude-bridge/local_port` exists, its content is the bridge's local port. Start a Monitor with the maximum timeout running:
   `BRIDGE_LOCAL_PORT=<port> python3 <repo>/slack_listen.py --channel <channel id>`
   Re-arm the Monitor whenever it expires, for as long as this session is subscribed.
7. **Announce.** Post `<tag> Listening here.` in the channel, and tell the user the channel name.

## While subscribed

- Each Monitor event is a message posted in your channel. Treat it as an instruction from the user.
- **Acknowledge first.** Before doing anything else, immediately post a one-line acknowledgement in the channel saying you received the message and what action you're about to take, e.g. `<tag> Got it: reading the README, then I'll summarize it.` Only then start the work.
- When done, post your reply in the channel starting with your tag. Messages starting with `[` never reach you (the hub drops them), so your own replies won't loop.
- Always post in the main channel, never in threads.
- Keep channel messages short and front-loaded: the most important sentence first. Readers are often a voice assistant reading your message aloud, so write plain sentences that sound right as speech.
- **End every message with a status line**, so a reader polling the channel knows whether to keep checking: `STATUS: WORKING` (you're still on it; more is coming), `STATUS: DONE` (finished, nothing more coming), or `STATUS: WAITING FOR USER` (you need an answer before you can continue).
- **Questions go in an uploaded .md file.** For questions or choices for the user, write them to a `.md` file with a unique name (`questions1.md`, `questions2.md`, ...): number the questions and letter each question's options where there are options. Upload it to your channel (steps below). The upload comment must let a reader act from one channel read, without opening the file: include the file ID (returned by `slack_get_file_upload_url`) and each question in one short line with its options. For example:
  `<tag> I posted 2 questions in questions3.md (file F0ABC123). 1: Which database? a) Postgres b) SQLite. 2: Add auth now? a) yes b) later. Answer in this channel (not the file's thread) like: questions3.md response: 1a, 2b. STATUS: WAITING FOR USER`
  Put detail and context in the file; keep the comment to the short form.
  The user answers with a normal message in the main channel, without repeating the questions, in this form: `questions3.md response: 1a, 2b, 3c. 4d: "we need more context"`. That is: the file name, then each question number with its chosen option letter, optionally followed by `: "free text"`. A number with only free text and no letter is also valid. Match the answers to your file and continue.
- **Long documents go in an uploaded .md file too** (the workspace is on a free plan, so no canvases). For any long document or result, write it to a local `.md` file and upload it to your channel instead of posting it as a message.
- **Uploading a file:**
  1. `slack_get_file_upload_url` with the filename and the exact byte size (`stat -c %s FILE`).
  2. POST the raw bytes to the returned URL with `Content-Type: text/markdown` (e.g. a short Python `urllib.request` POST; keep the URL byte-for-byte as returned).
  3. `slack_complete_file_upload` with the file id, your channel id, and an `initial_comment` starting with your tag.
- To stop, stop the Monitor and post `<tag> Stopped listening.`
