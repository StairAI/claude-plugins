---
description: Install Stair the careful way - review the plugin's code, explain the privacy notice, get the person's consent, then set up
argument-hint: [invite code]
---

You are helping the person set up Stair, this plugin, which records their Claude Code sessions in a Reasoning Ledger they own. Do the steps in order. Do not skip the review or the consent, and do not run setup until they have said yes.

The plugin's directory is `${CLAUDE_PLUGIN_ROOT}`. If that is not an absolute path, use the newest directory under `~/.claude/plugins/cache/stair-ai/stair/` (for `/stair-dev:install`: `~/.claude/plugins/cache/stair-ai-dev/stair-dev/`).

This plugin's name is the `name` in `.claude-plugin/plugin.json` there: `stair`, the release channel, or `stair-dev`, the staging channel, which writes to the staging ledger and installs side by side with `stair`. The steps below are written for `stair`. For `stair-dev`, the state directory is `~/.stair-dev` instead of `~/.stair` and the command is `stair-dev` instead of `stair`; never point the `stair` command at it.

1. **Review the code first, and report what it does.** Read these files of the plugin (they are small): `bin/stair`, `hooks/hooks.json`, `rl_plugin.py`, `mapper.py`. Tell the person, in plain words: which hooks it registers and what they do on each event; what it reads (the transcript Claude Code writes; nothing else on the machine); where data is sent (only to the endpoint given at setup, and the one-time viewer link request); that content is encrypted on this machine before upload with a key kept in `~/.stair/master.key`; and anything that looks wrong. If anything sends data anywhere else, hides what it does, or looks malicious, stop here and say so.

2. **Explain the privacy notice.** Read `PRIVACY.md` in the plugin directory and relay it in the person's own language, with its full meaning, not a one-line summary: what is recorded, what the ledger can and cannot see, where it is stored and who runs it, what they can do (view, rotate the key, stop, ask for deletion), what is not there yet (no sharing, no backup command, alpha). Say that file paths and tool names stay readable on the ledger, so a machine that works on something they must not share should not have the plugin.

3. **Ask for consent explicitly.** Ask one question: do they accept the notice (version `2026-10-29`) and want recording to start with their next session? Use AskUserQuestion when it is available; otherwise ask in the message and wait. Without a clear yes, stop; nothing is installed further and nothing has been sent.

4. **Set up.** Ask for a short name for this machine (such as "work-laptop") and the invite code if it was not given as the argument (`$ARGUMENTS`). No e-mail is needed: the account is anonymous and its keys are its identity; they can add an e-mail later with `stair rl claim you@example.com` so the account can be found again. Then run, with the real values:

   ```
   "${CLAUDE_PLUGIN_ROOT}/bin/stair" rl setup --agent-name NAME --invite CODE --accept-privacy-notice 2026-10-29
   ```

   The ledger it writes to is this channel's default (`channel.env` in the plugin directory: the hosted ledger `api.stair-ai.com` for `stair`, the staging ledger for `stair-dev`); `--endpoint` overrides it. It builds the plugin's Python environment (needs `uv` or Python 3.12+; `curl -LsSf https://astral.sh/uv/install.sh | sh` installs uv), creates the account, makes the keys, registers this machine and sends one probe record. Show the person the JSON line it prints. If it fails, show the error and stop; do not retry with other values on your own.

5. **Finish.** Tell them: back up `~/.stair/master.key` and `~/.stair/owner.key` now (the keys are the account; without the master key the content cannot be read); recording starts with the next session, or after `/reload-plugins`; `stair rl viewer` prints a one-time link to see their records, decrypted in the browser, and the link must not be shared because it carries their key; `stair rl claim you@example.com` attaches an e-mail whenever they want one. Offer to put the launcher on their PATH:

   ```
   ln -sf "${CLAUDE_PLUGIN_ROOT}/bin/stair" ~/.local/bin/stair        # stair, the release channel
   ln -sf "${CLAUDE_PLUGIN_ROOT}/bin/stair" ~/.local/bin/stair-dev    # stair-dev, the staging channel
   ```

   Run only the line for this plugin's name.
