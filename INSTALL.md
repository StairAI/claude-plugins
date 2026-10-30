# Installing Stair for Claude Code

These are instructions for the assistant. A person has asked you to install Stair, a Claude Code plugin that keeps a record of their sessions in a Reasoning Ledger they own, with the text encrypted on their machine. Do the steps in order; ask before each command the first time; do not skip the review or the consent.

## 1. Install the plugin

Run, from the shell:

```
claude plugin marketplace add StairAI/claude-plugins
claude plugin install stair@stair-ai
```

If the marketplace was added before, the first command says so; then run `claude plugin marketplace update stair-ai`, which fetches the newest version. If the plugin was installed before, the second command says so; then run `claude plugin update stair@stair-ai` after the marketplace update (on its own it compares against the old copy and finds nothing newer). If `uv` is missing and there is no Python 3.12 or newer on the machine, offer to install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`); the plugin builds its own Python environment with it.

## 2. Follow the plugin's own install command

The plugin is now at the newest directory under `~/.claude/plugins/cache/stair-ai/stair/` (`~/.claude/plugins/cache/stair-ai/stair/<version>/`, the highest version there). Read `commands/install.md` in that directory and follow it exactly. It has you:

1. read the plugin's code (`bin/stair`, `hooks/hooks.json`, `rl_plugin.py`, `mapper.py`) and tell the person what it does, what it reads, and where it sends data;
2. explain the privacy notice (`PRIVACY.md`) in the person's language, with its full meaning;
3. ask for their consent to notice version `2026-10-29`, and stop without a clear yes;
4. ask for a short name for this machine and their invite code (they may have given it in their message); no e-mail is needed, the account is anonymous and its keys are its identity; then run the setup command with `--accept-privacy-notice 2026-10-29`;
5. tell them to back up `~/.stair/master.key` and `~/.stair/owner.key`, that recording starts with the next session (or `/reload-plugins`), that `stair rl viewer` opens their records, and that `stair rl claim you@example.com` attaches an e-mail whenever they want one.

The endpoint is `https://api.stair-ai.com` unless the person says otherwise.

## 3. Finish

Say in two lines what was done: that an anonymous account was created, the machine's agent name, and that nothing is read from the machine except the transcripts Claude Code writes. From then on, at the start of a session, the plugin may leave a one-line notice from its makers (a new version, a changed privacy notice); relay it and ask before acting on it. Offer to link the launcher into their PATH:

```
ln -sf "$HOME/.claude/plugins/cache/stair-ai/stair/$(ls ~/.claude/plugins/cache/stair-ai/stair | sort -V | tail -1)/bin/stair" ~/.local/bin/stair
```

If anything fails, show the person the exact error and stop; do not retry with other values on your own.
