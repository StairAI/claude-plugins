# Installing Stair for Claude Code

These are instructions for the assistant. A person has asked you to install Stair, a Claude Code plugin that keeps a record of their sessions in an account of theirs, with the text encrypted on their machine. Do the steps in order; ask before each command the first time; do not skip the review or the question.

## 1. Install the plugin

Run, from the shell:

```
claude plugin marketplace add StairAI/claude-plugins
claude plugin install stair@stair-ai
```

If the marketplace was added before, the first command says so; then run `claude plugin marketplace update stair-ai`, which fetches the newest version. If the plugin was installed before, the second command says so; then run `claude plugin update stair@stair-ai` after the marketplace update (on its own it compares against the old copy and finds nothing newer). If `uv` is missing and there is no Python 3.12 or newer on the machine, offer to install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`); the plugin builds its own Python environment with it.

## 2. Follow the plugin's own install command

The plugin is now at the newest directory under `~/.claude/plugins/cache/stair-ai/stair/` (`~/.claude/plugins/cache/stair-ai/stair/<version>/`, the highest version there). Read `commands/install.md` in that directory and follow it exactly. The person sees three short steps; it has you:

1. read the plugin's code and its privacy notice (`PRIVACY.md`), then tell the person in three lines what it reads, where it sends data, and whether anything looks wrong;
2. show the notice's short version exactly as written, after the line "Nothing has been sent yet.", and ask one question, "Start recording from your next session?", with neither answer marked as recommended; stop without a clear yes;
3. run setup with their invite code (they may have given it in their message) and `--accept-privacy-notice 2026-11-12`: no e-mail and no machine name are needed (the machine is named after its kind unless they want another name); a machine that still has Stair's keys from an earlier install, or keys the person kept in a folder, reconnects that account instead (`--restore FOLDER`; never ask for the keys themselves); then say in two lines that the account is made and that the two key files are their account, to keep a copy of.

The endpoint is `https://api.stair-ai.com` unless the person says otherwise.

## 3. Finish

Offer to put the `stair` command on their PATH (a small script in `~/.local/bin` that always runs the installed version, so updates need nothing more):

```
"$HOME/.claude/plugins/cache/stair-ai/stair/$(ls ~/.claude/plugins/cache/stair-ai/stair | sort -V | tail -1)/bin/stair" link
```

From then on, the plugin can show the person a one-line notice at the start of a session, about a new version or a changed privacy notice. It speaks to them directly and they choose; a changed notice they accept by typing `/stair:notice` themselves. If anything fails, show the person the exact error and stop; do not retry with other values on your own.
