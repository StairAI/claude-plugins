---
description: Read Stair's privacy notice in short and choose whether it records - after the notice changed, or any time
---

The person typed this command to read Stair's privacy notice and choose. Only they decide; your part is to show the notice faithfully and do what they choose.

The plugin's directory is `${CLAUDE_PLUGIN_ROOT}`; its name is the `name` in `.claude-plugin/plugin.json` there (`stair`, or `stair-dev` for the staging channel, whose command is `stair-dev` and state directory `~/.stair-dev`).

1. Read `PRIVACY.md` in the plugin directory in full: you answer questions from it. Run `"${CLAUDE_PLUGIN_ROOT}/bin/stair" rl status` and note `privacy_notice` (the version they accepted, if any), `privacy_notice_installed`, `uploads_paused` and `waiting_sessions`. If `configured` is false, Stair is not set up on this machine: tell them `/stair:install` sets it up, and stop. If `uploads_paused` is true but the accepted version is already the installed one, the makers published a newer notice than this plugin has: offer to update the plugin (`claude plugin marketplace update stair-ai && claude plugin update stair@stair-ai`, for `stair-dev` the marketplace `stair-ai-dev`), which applies to sessions started after it, and stop here.

2. Show them, exactly as written (translate faithfully if they write in another language): when the accepted version is older than the installed one, first the line "Stair's privacy notice changed (ACCEPTED to INSTALLED). Nothing has been sent since; N sessions wait on this machine.", with the real versions and `waiting_sessions` for N; then the whole "In short" section of `PRIVACY.md`; then, when it changed, the newest entry of its "Changes to this notice" section; and last the line "The full notice is PRIVACY.md (version INSTALLED); ask me anything about it."

3. If the installed version is the accepted one, say they accepted it (with the date, from `accepted_at`) and that nothing needs doing; stop. Otherwise ask one question with AskUserQuestion, "Accept notice INSTALLED and go on recording?", none of the options marked as recommended: when sessions wait, "Yes, and send the N waiting sessions", "Yes, but leave the waiting sessions out" and "Not now"; when none wait, "Yes" and "Not now". Without AskUserQuestion, ask in the message and wait. Answer their questions from `PRIVACY.md` before they choose.

4. Do what they chose. Yes: run `"${CLAUDE_PLUGIN_ROOT}/bin/stair" rl accept-notice INSTALLED`, adding `--skip-waiting` if they chose to leave the waiting sessions out, and say in one line what it did (`waiting_sessions_sent`, `waiting_sessions_left_out`). Not now: change nothing, and say that nothing is sent until they accept, that `/stair:notice` brings them back here, and that `claude plugin uninstall stair@stair-ai` stops Stair altogether.
