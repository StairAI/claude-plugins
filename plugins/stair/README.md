# stair: the Stair plugin for Claude Code

Installs in a minute, then keeps a record of every turn of every session in a Reasoning Ledger you own: tool calls, questions and answers, decisions, outcomes, as schema 0.5 behavior records. The text of what happened (prompts, answers, what tools were given and returned) is encrypted on your machine with a key only you hold; the ledger sees the shape of the work, not its words. The transcript Claude Code writes is the source of truth; hooks only mark the moments and the few facts the transcript lacks. Nothing is asked of the model.

## Install (what the person does)

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

   By hand, the same thing: read `PRIVACY.md`, then run setup with the notice's version in `--accept-privacy-notice` (without it, setup prints the notice and stops). The launcher is `bin/stair` inside the installed copy, `~/.claude/plugins/cache/stair-ai/stair/<version>/`; link it somewhere on your PATH so the commands below read as written:

   ```bash
   ln -sf "$HOME/.claude/plugins/cache/stair-ai/stair/$(ls ~/.claude/plugins/cache/stair-ai/stair | sort -V | tail -1)/bin/stair" ~/.local/bin/stair
   stair rl setup --endpoint https://api.stair-ai.com --register you@example.com --agent-name "my-laptop" --invite STAIR-XXXXX-XXXXX --accept-privacy-notice 2026-10-29
   ```

   The setup builds the plugin's own Python environment (with `uv`, or Python 3.12+), creates your owner on the ledger with your invite code, makes your content master key, registers this machine as an agent and sends one probe record (which carries the notice version you accepted). Two files come out of it, both readable by you only and never printed or sent:

   - `~/.stair/owner.key`, the key that writes to your account;
   - `~/.stair/master.key`, the key that encrypts your content. **Back this one up** (copy it somewhere safe): without it, nobody can read the content, you included.

   The invite code is kept in `~/.stair/config.json`, so a later setup on this machine does not ask for it again. With an owner key you were given instead of `--register`: `--api-key-file <file>`. On a self-hosted ledger that does not allow self-service, put its registration token in `STAIR_REGISTRATION_TOKEN` (or `--registration-token-file`); `--plaintext` turns encryption off there, if its operator wants readable content. Where the SDK should come from is `STAIR_SDK_SPEC` (a pip requirement; default: the ledger repository's `develop` branch).

3. Start a new session (or `/reload-plugins`). From the next turn on, every turn of every session is recorded.

`/stair:install` is the plugin's one slash command (`commands/install.md`): a review of the plugin's own code, the notice, the question, then the setup command. Claude is not asked to do anything else, ever: recording comes from the transcript and the hooks, not from the model.

## Looking at your ledger

`stair rl viewer` prints a one-time link to the trace viewer, valid for ten minutes: one row per turn, and a graph of each turn's records with the text decrypted in your browser. The link carries your content master key after `#`, which the browser keeps to itself and never sends to the server; share the link with nobody (`--no-key` leaves the key out, and the content then stays encrypted on the page). When the viewer is reached at another address than the upload endpoint, pass it once with `stair rl viewer --base https://… --save` (or `--viewer-url` at setup).

| Command | What it does |
|---|---|
| `stair rl status` | Where this machine writes, how much it has uploaded, what is queued or spooled, whether encryption is on |
| `stair rl viewer [--next /traces/…] [--no-key]` | A one-time sign-in link (see above) |
| `stair rl flush` | Retry the records the server rejected or that waited for an upstream |
| `stair rl map <transcript.jsonl>` | Dry run: map a transcript to records without uploading |
| `stair rl key id` / `stair rl key rotate` | The content master key's id; or a new key, with every session key the ledger holds re-wrapped under it (the old key stays in `master.key.old`) |
| `stair rl admin new --count 5 --note "…" --admin-token-file <file>` | Operators: make invite codes (`list`, `revoke <code>`); the administrator token is read from a file, never passed as an argument |
| `stair env` | Rebuild the plugin's Python environment |

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
| The transcript (rules) | `Observing` (each prompt), `ToolCalling` (each call: id, duration, outcome, effect; file writes as pointers), `Delegating` (sub-agents, messages), `Escalating` + `Attesting` (questions and their answers), `Memorizing` (writes to memory files, CLAUDE.md, skills, settings), `Thinking` (thinking blocks), `Planning` (plan tools, and a reply that lays out a numbered plan), `Reflecting` (after test or lint commands; verdict sentences in the agent's own text), `Acting` (`answer.final`), `Other` (narration, compaction) |
| Hook events merged in | `Escalating` + `Attesting` for permission prompts (approve / reject / no_response), sub-agent sessions |

Every record has two layers. The structure stays readable on the ledger: behavior, timing, outcome, duration, tool names, token counts, file paths in pointers, the size of each text. The content positions (the prompt, the answer, what a tool was given and returned, what was asked, what was delegated) are encrypted on this machine before upload, with a data key per session that the ledger holds only wrapped under your master key. Thinking blocks go further: by default the ledger gets only a fingerprint of each block (its size and SHA-256), itself encrypted like any content; the text stays on the machine (`thinking_text: "hash"` in `config.json`; `"full"` uploads the text, encrypted). The ledger's administrator can read the structure and the ciphertext, and nothing else.

Rewind and fork of a conversation are represented, not erased: see `../LEDGER_GUIDE.md` section 5.

## Files

- `hooks/hooks.json`, `bin/stair` (bash fast path + python entry), `rl_plugin.py` (processor, setup, status, flush, map, viewer, key, admin), `mapper.py` (transcript to records), `PRIVACY.md` (the notice setup asks you to accept), `commands/install.md` (`/stair:install`).
- `../LEDGER_GUIDE.md` (repository root) - the eleven behaviors, their fields, and the rules this plugin maps Claude Code's transcript by.
- `experiment/` - the headless experiment and install-test runners; `tests/` - mapper rules on synthetic transcripts (turns, rewind, fork, plans, verification reads, questions, schema validity) and the setup, viewer, key and admin commands.

State: `$STAIR_HOME` (default `~/.stair`; an install made under the plugin's earlier name, `~/.stair-rl`, is moved over on first use): `config.json`, `owner.key`, `master.key`, `queue/events.jsonl`, `state/<transcript>.json` (what was uploaded), `spool.jsonl` (records the server rejected, with its reason, and records held back because their upstream failed; `stair rl flush` retries), `logs/`.

## Limits of this version

- The master key is one file on one machine. Back it up yourself; `stair access backup` is for a later version. A second machine of yours is a second agent with its own key (the ledger can hold several), not a copy of this one.
- Sharing a session with someone else, or letting an evaluator read it, means wrapping that session's key for them. The ledger has the place for it; the commands do not exist yet.
- The whole transcript is re-mapped on every turn; long transcripts will want offset-based incremental mapping.
- Plan tools (TodoWrite and the plan-mode tools) are written as `Planning` with the todo items as `steps`.
- The SDK is the Python SDK installed from the ledger repository's `develop` branch (`STAIR_SDK_SPEC`), not a published package yet; a development checkout (`STAIR_SDK_SRC`) is used when present.
