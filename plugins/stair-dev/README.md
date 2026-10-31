# stair: the Stair plugin for Claude Code

Installs in a minute, then keeps a record of every turn of every session in a Reasoning Ledger you own: tool calls, questions and answers, decisions, outcomes, as schema 0.5 behavior records. The text of what happened (prompts, answers, what tools were given and returned) is encrypted on your machine with a key only you hold; the ledger sees the shape of the work, not its words. The transcript Claude Code writes is the source of truth; hooks only mark the moments and the few facts the transcript lacks. Nothing is asked of the model.

## Install (what the person does)

The whole install is one message in a Claude Code session:

> Install Stair for me: follow https://raw.githubusercontent.com/StairAI/claude-plugins/main/INSTALL.md. My invite code is STAIR-XXXXX-XXXXX.

Claude installs the plugin, reads its code and says what it does, explains the privacy notice, asks for consent, and only then runs the setup (the instructions it follows are `INSTALL.md` in the public marketplace repository, which points at `commands/install.md` here). The same by hand:

1. Add the marketplace and install the plugin, once per machine:

   ```bash
   claude plugin marketplace add StairAI/claude-plugins
   claude plugin install stair@stair-ai
   ```

   (Working from the source repository instead, which is private: `claude plugin marketplace add git@github.com:StairAI/Reasoning-Ledger-Integrations.git`, with access to it on GitHub and a GitHub SSH key on the machine.)

2. Set it up once. The easiest way is to let Claude do it, carefully: in a Claude Code session, type

   ```
   /stair:install STAIR-XXXXX-XXXXX
   ```

   Claude then reads the plugin's code and tells you what it does and where it sends data, explains the privacy notice ([`PRIVACY.md`](./PRIVACY.md)) in your language, asks whether you accept it, and only then runs the setup below with your e-mail, a name for this machine and your invite code. Nothing is registered or sent before you say yes.

   By hand, the same thing: read `PRIVACY.md`, then run setup with the notice's version in `--accept-privacy-notice` (without it, setup prints the notice and stops). The launcher is `bin/stair` inside the installed copy, `~/.claude/plugins/cache/stair-ai/stair/<version>/`; its `link` command puts `stair` on your PATH (`~/.local/bin/stair`, a small script that runs whichever version Claude Code has installed), so the commands below read as written:

   ```bash
   "$HOME/.claude/plugins/cache/stair-ai/stair/$(ls ~/.claude/plugins/cache/stair-ai/stair | sort -V | tail -1)/bin/stair" link
   stair rl setup --agent-name "my-laptop" --invite STAIR-XXXXX-XXXXX --accept-privacy-notice 2026-10-30.2
   ```

   The setup builds the plugin's own Python environment (with `uv`, or Python 3.12+), creates your owner on the ledger with your invite code (anonymous: the keys are the identity; `--register you@example.com` registers with an e-mail instead, and `stair rl claim you@example.com` attaches one later), makes your content master key, registers this machine as an agent and sends one probe record (which carries the notice version you accepted). Two files come out of it, both readable by you only and never printed or sent:

   - `~/.stair/owner.key`, the key that writes to your account;
   - `~/.stair/master.key`, the key that encrypts your content. **Back this one up** (copy it somewhere safe): without it, nobody can read the content, you included.

   Installed again after an uninstall, which leaves `~/.stair` as it is, setup reconnects the same account by itself: no invite code, the machine's earlier name, the same records. Keys kept elsewhere come back with `--restore <folder>` (the folder holding `owner.key` and `master.key`, or a copy of `~/.stair`). Before writing anything, setup checks with the ledger that it accepts the owner key and that the master key opens this machine's sessions there, and stops when it does not (`--new-master-key` starts a new key, the earlier sessions then staying unreadable). A different key already here is moved aside as `<name>.replaced-<time>` with `--force`, never deleted.

   The invite code is kept in `~/.stair/config.json`, so a later setup on this machine does not ask for it again. With an owner key you were given instead of `--register`: `--api-key-file <file>`. On a self-hosted ledger that does not allow self-service, put its registration token in `STAIR_REGISTRATION_TOKEN` (or `--registration-token-file`); `--plaintext` turns encryption off there, if its operator wants readable content. Where the SDK should come from is `STAIR_SDK_SPEC` (a pip requirement; default: the ledger repository's `develop` branch).

3. Start a new session (or `/reload-plugins`). From the next turn on, every turn of every session is recorded.

`/stair:install` is the plugin's one slash command (`commands/install.md`): a review of the plugin's own code, the notice, the question, then the setup command. Claude is not asked to do anything else, ever: recording comes from the transcript and the hooks, not from the model.

## Looking at your ledger

`stair rl viewer` opens the trace viewer by way of a view grant: your sessions of the last seven days (`--days`), for an hour (`--hours`), as one row per conversation and a graph of each turn's records, with the text decrypted in your browser. The plugin unwraps those sessions' data keys here with your master key, wraps them again under a fresh grant key and registers the grant with the ledger (2.1.0 or later), which keeps the re-wrapped keys until the grant ends and then drops them; the link carries the grant key after `#`, which the browser never sends, and the grant is recorded in your ledger. The master key never leaves the machine. The link is opened in this machine's browser, or printed only in a terminal of your own: run by Claude on a machine without a browser, the command says so and prints no key. `--no-key` gives a one-time link to the structure, without any key. When the viewer is reached at another address than the upload endpoint, pass it once with `stair rl viewer --base https://… --save` (or `--viewer-url` at setup).

| Command | What it does |
|---|---|
| `stair rl status` | Where this machine writes, under which name, how much it has uploaded, what is queued or spooled, whether encryption is on, whether the keys are here |
| `stair rl setup --restore <folder>` | Reconnect the account whose keys you kept (no invite code); see Install |
| `stair rl viewer [--days 7] [--hours 1] [--no-key]` | Open a view grant in the browser (see above) |
| `stair rl grants` / `stair rl revoke <grant>` | Your view grants; end one now (the ledger drops its keys and signs its browsers out) |
| `stair rl flush` | Retry the records the server rejected or that waited for an upstream |
| `stair rl map <transcript.jsonl>` | Dry run: map a transcript to records without uploading |
| `stair rl claim you@example.com` | Attach an e-mail to this anonymous account (409 if another account has it) |
| `stair rl notices [--fetch]` / `stair rl accept-notice <version>` | What the makers published for this install (a newer version, a changed privacy notice); accept the current `PRIVACY.md` after reading it, which resumes recording |
| `stair rl key id` / `stair rl key rotate` | The content master key's id; or a new key, with every session key the ledger holds re-wrapped under it (the old key stays in `master.key.old`) |
| `stair rl admin new --count 5 --note "…" --admin-token-file <file>` | Operators: make invite codes (`list`, `revoke <code>`); the administrator token is read from a file, never passed as an argument |
| `stair env` | Rebuild the plugin's Python environment |

## Other Stair services: `stair access`

The owner key goes only to the ledger and its access gate. Other Stair services the account can reach, the first being the team's page sharing at `share.stair-ai.com`, receive a short-lived token bound to that one service instead, which `stair access` gets from the gate in exchange for the key (RFC 8693 token exchange). A service is reached only after the Stair administrator has granted it to the account, and pages and files there live under the account's handle, which the administrator gives too.

| Command | What it does |
|---|---|
| `stair access token --resource https://share.stair-ai.com` | Print a token for one service, for a program to read (a skill's script); a cached token is reused while it has five minutes left, `--fresh` asks again |
| `stair access me` | This account's owner id, handle and the services it may reach; send the owner id to the administrator to be given access |
| `stair access admin handle <owner> <handle>` | Operators: give an owner (id or e-mail) its handle; changing an existing one needs `--replace`, since links under it stop working |
| `stair access admin grant <owner> <service> <scope>…` | Operators: let an owner reach a service, e.g. `grant colin@stair-ai.com https://share.stair-ai.com share:write`; `grants`, `revoke <id>` and `lookup` too. The administrator token comes from `--admin-token-file` or `STAIR_ADMIN_TOKEN` |

## Notices from the makers

The plugin checks a public file beside the published plugin (`notices.json` on the channel's own branch of `StairAI/claude-plugins`: `main` for `stair`, `staging` for `stair-dev`; `STAIR_NOTICES_URL` in `channel.env`) at most hourly, after an upload run, never from a hook. What applies to this install and was not shown yet, a newer published version, a privacy notice newer than the accepted one, or a message, is left in `~/.stair/notice.pending.json`; the `SessionStart` hook prints it once, as one line for the person (`systemMessage`, which may quote the file) and, for Claude, sentences built on this machine from version numbers only (`additionalContext`), never the file's text: whoever can change that file could otherwise instruct every installed assistant. When the person asks what an update changes, Claude reads the new version's `CHANGES.md`, and nothing interrupts a session in progress. A changed privacy notice pauses uploads (the queue keeps growing on the machine) until `stair rl accept-notice <version>` is run with the installed `PRIVACY.md`'s version, after the person has read it. `stair rl notices --fetch` shows the state now. Updating is `claude plugin marketplace update stair-ai && claude plugin update stair@stair-ai` (for `stair-dev`: `stair-ai-dev` and `stair-dev@stair-ai-dev`), the marketplace first: `claude plugin update` alone compares against the local copy of the marketplace and finds nothing newer. The new version applies to sessions started after it.

## How it works (the batch design)

| Moment | Hook | What happens | Cost on the session |
|---|---|---|---|
| A permission prompt appears, or is denied | `PermissionRequest`, `PermissionDenied` | one line appended to the local queue | about 10 ms |
| A sub-agent finishes | `SubagentStop` | one line appended (where its transcript is) | about 10 ms |
| The model finishes a turn | `Stop` | one line appended; a detached processor is started | about 10 ms |
| The session closes | `SessionEnd` | same, as a fallback | about 10 ms |

The processor (`stair rl process`) waits a moment for the transcript to settle, maps the whole transcript with `mapper.py`, encrypts and uploads the records not uploaded before (in batches of 50, content first, through the Python SDK) and remembers them per transcript. Records carry `client_ts_utc` from the transcript, so uploading later changes nothing about when things happened; the server stamps receipt time and a sequence number.

Tool calls, prompts and the final answer are never recorded by hooks: they come from the transcript, with more detail than a hook sees (token usage, cache, model, request id).

## What gets recorded, and what the ledger can read

| From | Behaviors |
|---|---|
| The transcript (rules) | `Observing` (each message that opens a turn; who sent it, the person, another session or agent, a finished background task or the app, comes from the line's origin), `ToolCalling` (each call: id, duration, outcome, effect; file writes as pointers), `Delegating` (sub-agents, sessions started or handed over, messages; the started session's first turn carries the same `link:` tag), `Escalating` + `Attesting` (questions and their answers), `Memorizing` (writes to memory files, CLAUDE.md, skills, settings), `Thinking` (thinking blocks), `Planning` (plan tools, and a reply that lays out a numbered plan: the shape of the plan; its words travel as the tool call's input or a companion `Thinking` output), `Reflecting` (after test or lint commands; verdict sentences in the agent's own text, kept as length and digest with the sentence inside the encrypted output), `Acting` (`answer.final`), `Other` (narration, compaction) |
| Hook events merged in | `Escalating` + `Attesting` for permission prompts (approve / reject / no_response), sub-agent sessions |

Every record has two layers. The structure stays readable on the ledger: behavior, timing, outcome, duration, tool names, token counts, the size of each text, the number of steps in a plan, the kind of a question or permission, the class of an error. The content positions (the prompt, the answer, what a tool was given and returned, what was asked with its options, what was delegated, the wording of plans and verdicts, file pointers and memory targets) are encrypted on this machine before upload, with a data key per session that the ledger holds only wrapped under your master key. A test (`test_no_words_of_the_session_sit_outside_content_positions`) checks that no word of a session appears outside the content positions. Thinking blocks go further: by default the ledger gets only a fingerprint of each block (its size and a keyed hash: HMAC-SHA256 with a key derived from your master key, like every content fingerprint since 0.11.2) (records uploaded before 0.11.2 keep plain SHA-256 fingerprints, the ledger never rewriting a record; and since fingerprints follow the master key, records written after `stair rl key rotate` no longer match those written before), itself encrypted like any content; the text stays on the machine (`thinking_text: "hash"` in `config.json`; `"full"` uploads the text, encrypted). The ledger's administrator can read the structure and the ciphertext, and nothing else.

Rewind and fork of a conversation are represented, not erased: see `../LEDGER_GUIDE.md` section 5. A fork made by the Claude app copies the parent's history into the new transcript; that copy is not uploaded again (it was recorded in the parent session), and the fork's first turn points back at it. Records written before 0.11.0 keep the attribution they were written with: the ledger is append-only.

## Files

- `hooks/hooks.json`, `bin/stair` (bash fast path + python entry), `rl_plugin.py` (processor, setup, status, flush, map, viewer, key, admin), `access.py` (`stair access`: tokens for other Stair services, handles and grants), `mapper.py` (transcript to records), `PRIVACY.md` (the notice setup asks you to accept), `commands/install.md` (`/stair:install`).
- `../LEDGER_GUIDE.md` (repository root) - the eleven behaviors, their fields, and the rules this plugin maps Claude Code's transcript by.
- `experiment/` - the headless experiment and install-test runners; `tests/` - mapper rules on synthetic transcripts (turns, rewind, fork, plans, verification reads, questions, schema validity) and the setup, viewer, key and admin commands; `stair access` against a stand-in gate.

State: `$STAIR_HOME` (default `~/.stair`; an install made under the plugin's earlier name, `~/.stair-rl`, is moved over on first use): `config.json`, `owner.key`, `master.key`, `access.json` (cached service tokens and the gate's address), `queue/events.jsonl`, `state/<transcript>.json` (what was uploaded), `spool.jsonl` (records the server rejected, with its reason, and records held back because their upstream failed; `stair rl flush` retries), `logs/`.

## Channels: `stair` and `stair-dev`

The same source builds two plugins that can be installed side by side. `stair`, from the public marketplace's `main` branch, is the release channel: it writes to the hosted ledger and its Python environment is pinned to a release of the ledger repository. `stair-dev`, from the same marketplace's `staging` branch (`claude plugin marketplace add StairAI/claude-plugins#staging`, then `claude plugin install stair-dev@stair-ai-dev`), is the staging channel: it writes to the staging ledger, follows the ledger repository's `develop` branch, and gets every version before the release channel does. Each keeps its state under `~/.<name>` (`~/.stair`, `~/.stair-dev`), its commands are namespaced by its name (`/stair:install`, `/stair-dev:install`), and with both installed every turn is recorded twice, each by its own code into its own ledger. The channel's defaults are `channel.env` in the plugin directory; `publish.sh` writes each channel's values into the copy it publishes, and each channel reads the notices of its own branch. To run code that is not published yet, `claude --plugin-dir ./claude-code` loads this directory for one session (disable the installed `stair-dev` first, or that turn is recorded by both).

## Limits of this version

- The master key is one file on one machine. Back it up yourself (copy `owner.key` and `master.key`); `setup --restore` puts them back, on this machine or another. A second machine joins the same account with `--restore` and a new `--agent-name`: with both keys it shares this master key, with `owner.key` alone it makes its own.
- Sharing a session with someone else, or letting an evaluator read it, means wrapping that session's key for them. The ledger has the place for it; the commands do not exist yet.
- The whole transcript is re-mapped on every turn; long transcripts will want offset-based incremental mapping.
- Plan tools (TodoWrite and the plan-mode tools) are written as a `ToolCalling` (the items, encrypted) plus a `Planning` whose `steps` carry only each item's length.
- The SDK is the Python SDK installed from the ledger repository's `develop` branch (`STAIR_SDK_SPEC`), not a published package yet; a development checkout (`STAIR_SDK_SRC`) is used when present.
