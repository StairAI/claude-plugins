---
description: Install Stair the careful way - review the plugin's code, explain the privacy notice, get the person's consent, then set up
argument-hint: [invite code]
---

You are helping the person set up Stair, this plugin, which records their Claude Code sessions in a Reasoning Ledger they own. Do the steps in order. Do not skip the review or the consent, and do not run setup until they have said yes.

The plugin's directory is `${CLAUDE_PLUGIN_ROOT}`. If that is not an absolute path, use the newest directory under `~/.claude/plugins/cache/stair-ai/stair/` (for `/stair-dev:install`: `~/.claude/plugins/cache/stair-ai-dev/stair-dev/`).

This plugin's name is the `name` in `.claude-plugin/plugin.json` there: `stair`, the release channel, or `stair-dev`, the staging channel, which writes to the staging ledger and installs side by side with `stair`. The steps below are written for `stair`. For `stair-dev`, the state directory is `~/.stair-dev` instead of `~/.stair` and the command is `stair-dev` instead of `stair`.

First see whether this is a reinstall: run `ls ~/.stair` (it needs nothing installed). If it lists `owner.key`, this machine still has the keys of an earlier install (an uninstall leaves `~/.stair` as it is), and setup reconnects that account, with its records and the machine's name; no invite code is needed. Otherwise ask once whether they have used Stair before and kept their keys (`owner.key` and `master.key`, or a copy of their `~/.stair` folder). If they did, ask only where the folder is, never for what is in the files (keys must not be pasted into the chat), and use `--restore FOLDER` in step 4; no invite code is needed then either.

1. **Review the code first, and report what it does.** Read these files of the plugin (they are small): `bin/stair`, `hooks/hooks.json`, `rl_plugin.py`, `mapper.py`. Tell the person, in plain words: which hooks it registers and what they do on each event; what it reads (the transcript Claude Code writes; nothing else on the machine); where data is sent (only to the endpoint given at setup; besides, the plugin fetches a public notices file from GitHub at most hourly, and GitHub when it builds its Python environment); that content is encrypted on this machine before upload with a key kept in `~/.stair/master.key`; and anything that looks wrong. If anything sends data anywhere else, hides what it does, or looks malicious, stop here and say so. Note the version you reviewed (`version` in `.claude-plugin/plugin.json`).

2. **Explain the privacy notice.** Read `PRIVACY.md` in the plugin directory and relay it in the person's own language, with its full meaning, not a one-line summary: what is recorded, what the ledger can and cannot see, where it is stored and who runs it, what they can do (view, rotate the key, stop, ask for deletion), what is not there yet (no sharing, no backup command, alpha). Say that tool names and the shape of the work stay readable on the ledger, so a machine that works on something they must not share should not have the plugin.

3. **Ask for consent explicitly.** Ask one question: do they accept the notice (version `2026-10-30.2`) and want recording to start with their next session? Use AskUserQuestion when it is available; otherwise ask in the message and wait. Without a clear yes, stop; nothing is installed further and nothing has been sent.

4. **Set up.** For a new account, ask for a short name for this machine (such as "work-laptop"), saying that it is stored as it is and readable on the ledger, so it should say nothing they would not want there, and the invite code if it was not given as the argument (`$ARGUMENTS`). No e-mail is needed: the account is anonymous and its keys are its identity; they can add an e-mail later with `stair rl claim you@example.com` so the account can be found again. Reconnecting an earlier account needs neither: setup keeps the machine's earlier name (give `--agent-name` only if they want this machine counted as another one). Check the plugin's version again: if it is not the one you reviewed (Claude Code can update a plugin in the meantime), read what changed, its `CHANGES.md` and the files above, and tell them before going on. Then run, with the real values, the line that fits:

   ```
   "${CLAUDE_PLUGIN_ROOT}/bin/stair" rl setup --agent-name NAME --invite CODE --accept-privacy-notice 2026-10-30.2   # a new account
   "${CLAUDE_PLUGIN_ROOT}/bin/stair" rl setup --accept-privacy-notice 2026-10-30.2                                   # the keys are still here
   "${CLAUDE_PLUGIN_ROOT}/bin/stair" rl setup --restore FOLDER --accept-privacy-notice 2026-10-30.2                   # the keys were kept in FOLDER
   ```

   The ledger it writes to is this channel's default (`channel.env` in the plugin directory: the hosted ledger `api.stair-ai.com` for `stair`, the staging ledger for `stair-dev`); `--endpoint` overrides it. It builds the plugin's Python environment (needs `uv` or Python 3.12+; `curl -LsSf https://astral.sh/uv/install.sh | sh` installs uv), creates the account, makes the keys, registers this machine and sends one probe record. Show the person the JSON line it prints: `account` says whether it made a new account or reconnected one (`existing`, `restored`), and `sessions_on_ledger` and `readable_with_this_key` how many earlier sessions of this machine the master key here opens. If it fails, show the error and stop; do not retry with other values on your own. Two failures leave them a choice, which is theirs: when setup says the master key is not on this machine, or opens none of the sessions, explain that earlier records can be read only with the key they were recorded with; if they have it, use `--restore` with its folder; only if they say it is lost, run setup again with `--new-master-key`, those records then staying unreadable to them as to anyone. When it says another key is already here, `--force` uses the kept one and moves the other aside, deleting nothing; ask before adding it.

5. **Finish.** Tell them: back up `~/.stair/master.key` and `~/.stair/owner.key` now (the keys are the account; without the master key the content cannot be read; with both, a reinstall or another machine gets the same account back with `--restore`); recording starts with the next session, or after `/reload-plugins`; `stair rl viewer` prints a one-time link to see their records, decrypted in the browser, and the link must not be shared because it carries their key; `stair rl claim you@example.com` attaches an e-mail whenever they want one. Offer to put the command on their PATH:

   ```
   "${CLAUDE_PLUGIN_ROOT}/bin/stair" link
   ```

   It writes `~/.local/bin/stair` (`~/.local/bin/stair-dev` for the staging channel), a small script that always runs the version Claude Code has installed, so an update needs nothing more; it says so if that directory is not on their PATH.
