# Changes

What each version of the Stair plugin for Claude Code changes for the person using it, newest first. When a newer version is out, the plugin says so at the start of a session together with the entries between your version and the new one, and Claude tells you more when you ask. A line that starts with "You do:" is something you have to do; it is said first.

## 0.17.0

Images that a tool returns, such as a screenshot or a picture Claude reads, stay on this machine.

- The record keeps, in each image's place, its type, its size and a fingerprint, the way it already does for thinking blocks; the picture itself is not sent. Text that a tool returns beside an image is sent as before, encrypted.
- To send images as well, encrypted like the rest, set `"image_content": "full"` in the plugin's `config.json`.
- On a busy machine we measured, such images were about two thirds of everything sent, by size, so sessions that look at screenshots now send much less.
- Privacy: the notice is unchanged (version 2026-11-12). It says a tool call's output is recorded; images are now left out of it, which its next version will say.

## 0.16.1

After an update, Claude asks you to switch an open session over, and what it records waits for the new privacy notice (2026-11-12).

- You do: after this update, type /reload-plugins in the prompt box (or start a new session), then /stair-dev:notice once to read what changed in the notice and accept it. Only you can type /reload-plugins; over Remote Control or on the phone, start a new session instead.
- From this version on, a session that is open when an update is installed hands what it records to the new version at once, and Claude asks you, once, to type /reload-plugins so that its commands switch too. Before, an open session went on recording and sending with the version it started with until it ended.
- When you say "update stair", Claude's plan ends with asking you to type /reload-plugins.
- /stair-dev:notice and /stair-dev:app say so when the session still runs an earlier version than the one installed; /stair-dev:notice asks you to reload first, since the notice it would show is the earlier version's.
- /stair-dev:notice counts the sessions recorded under the new notice, this one included, and says what leaving them out does to this session. A session recorded only before the update is not part of the choice: it goes under the notice you had accepted.
- Privacy: notice version 2026-11-12 says what happens to a session that is open during an update, and which sessions the choice after a change is about. What is recorded for you, and how, is unchanged.

## 0.16.0

Stair apps: `/stair-dev:app` lists the Stair services your account may use and does what you ask with one, starting with share, which publishes a page for your team. The privacy notice says what an app gets (version 2026-11-11).

- You do: after the update, type /stair-dev:notice once to read what changed in the notice and accept it. Until then nothing is sent; the sessions in between wait on this machine, and you choose whether they are sent.
- `/stair-dev:app share <file or folder>` publishes a page at share.stair-ai.com under your handle; `/stair-dev:app` with nothing after it lists your apps. Today only Stair's team has access to an app; for anyone else the list is empty.
- Before anything goes to an app, Claude says which files, where they go and who can open them. A page is not encrypted, and anyone with its link can open it.
- `stair-dev access apps` lists the same apps for a program, each with its address and its own documentation.
- /stair-dev:notice now shows every change to the notice since the version you accepted, not only the newest.
- Privacy: notice version 2026-11-11 adds "What do Stair's apps send?". What is recorded for you, and how, is unchanged.

## 0.15.3

After an update, a session you opened before it goes on recording without rebuilding anything.

- When an update brings a new version of the ledger SDK, the plugin builds the new Python environment and keeps the previous one for a week. Before, a session still open on the previous version rebuilt its environment, which takes about a minute, and removed the new one, so the two versions took turns rebuilding.
- A week on, the previous environment is removed. Until then it takes about 10 to 30 MB.
- From this version on, a session whose environment has been removed hands its recording to the version installed now, instead of building the environment again. This helps from the next update on.

## 0.15.2

/stair-dev:notice counts only the sessions that can still be sent and no longer says they were sent before they are; uploads keep the order things happened in.

- The number of waiting sessions leaves out any whose record has gone from this machine. If there are some, you are told how many could not be sent.
- After you accept, Claude says the waiting sessions start uploading when the turn ends and go on in the background; a long history can take hours.
- A record that got through only on a retry now counts as uploaded, so the total in `stair-dev rl status` is right and the session does not send it again.
- Records go up in the order they happened. After you stopped a turn, the records that followed were refused on the first try and waited for the retry ten minutes later; now they go through at once.
- A sub-agent that was continued, and so finished twice, is recorded once: its records no longer go up twice, and a sub-agent started after it keeps the link to the call that started it.
- On the staging channel, the commands, the privacy notice and the plugin's messages give the staging plugin's own command, slash commands and folder, so following them no longer acts on the release installed beside it.

## 0.15.1

Stair's one line at the start of a session comes less often and says which channel it is from.

- The line is shown only when you start a new session, not when one resumes, is cleared, is compacted or is forked.
- The reminder that the privacy notice changed comes at most once a day. Choose "Not now" in /stair-dev:notice and it stays quiet for a week; nothing is sent meanwhile.
- The line starts with the channel: "Stair" for the release, "Stair staging" for the staging channel. It now reads: "the privacy notice was updated. Your sessions stay on this machine until you choose — type /stair-dev:notice."
- When the question box cannot be shown, /stair-dev:notice asks the same question in plain text.

## 0.15.0

Setting up Stair is shorter, and calmer: Claude reads the plugin's code and says in three lines what it found, shows you a short notice as written and asks one question.

- Privacy: the notice is rewritten (version 2026-10-31) as questions and answers with a short version first. It now says why Stair keeps the record, and that each encrypted text carries a digest that a very short text can be guessed from. What is recorded and sent is unchanged.
- You do: after the update, type /stair-dev:notice once to read the short notice and accept it. Until then nothing is sent; the sessions in between wait on this machine, and you choose whether they are sent.
- Leave a project out with `stair-dev rl exclude <folder>`: sessions that work there are not recorded from then on.
- See what would be sent for your last turn, without sending it: `stair-dev rl preview`.
- A changed notice no longer has Claude ask for your consent: the plugin tells you in one line, and you choose by typing /stair-dev:notice.
- A new account names this machine after its kind (claude-code-mac, say) instead of asking, and the machine's id is sent as a fingerprint made with your key.

## 0.14.0

Installing Stair again gets your account back: the same records, no invite code, from the keys on this machine or the ones you kept.

- An uninstall leaves your keys in `~/.stair-dev`, and setup now reconnects that account by itself, keeping this machine's earlier name; `/stair-dev:install` checks for them first.
- Keys you kept elsewhere come back with `stair-dev rl setup --restore <folder>`, the folder that holds `owner.key` and `master.key`. Claude asks where the folder is, never for the keys.
- Before writing anything, setup checks with the ledger that your keys are the right ones: when the master key here cannot open your earlier sessions, it stops and says so instead of quietly making a new one.
- A key is never deleted: one that is replaced is moved aside as `<name>.replaced-<time>`.

## 0.13.1

`stair-dev access` now says plainly when your ledger does not run the Stair gate yet, where before it stopped with an error trace.

- An older ledger answers the gate's address with its sign-in page; the plugin now reads that as no gate, and any other answer that is not JSON as a one-line error.

## 0.13.0

Your account can now reach other Stair services, the first being the team's page sharing at share.stair-ai.com.

- `stair-dev access token --resource <address>` gives a skill a short-lived token for that one service. Your keys stay on this machine and go only to the Stair gate; the service never sees them.
- `stair-dev access me` shows your handle and the services your account may reach. Who may use which service is set by the Stair operator.

## 0.12.4

A long upload, such as the first after an update, no longer leaves failed pieces for you to retry by hand.

- Records that failed to upload for a passing reason, such as the network, are sent again by the plugin itself, at most every ten minutes.
- Privacy notice versions of the same day compare by number, so a tenth version of a day comes after the second.

## 0.12.3

The first session after an update says when recording is paused for a privacy notice, even on a machine that never fetched one.

- Privacy: when the plugin's own privacy notice is newer than the one you accepted, recording pauses, and every session says so from its first turn until you accept it, without the network.
- `stair-dev rl flush` sends nothing while recording is paused, and when the ledger cannot be reached it keeps everything to retry; `stair-dev rl status` counts it.

## 0.12.2

Several sessions open at once no longer lose or repeat each other's records.

- With several Claude Code sessions open, the uploads after each turn no longer run over one another: one at a time takes the queue, moving it aside first, so an event that arrives meanwhile waits for the next round instead of being lost.
- A record the ledger's rules rule out is set aside (`spool.invalid.jsonl`, counted in `stair-dev rl status`) instead of being retried forever.
- The plugin run from its source directory keeps its state apart (`~/.stair-dev-src`), so a development copy never shares a queue with the installed plugin.

## 0.12.1

A message to another session no longer names its recipient, and the privacy notice says where the viewer's protection ends.

- Privacy: a message sent to another session or agent no longer writes the recipient's name, often a session's title, where the ledger can read it; only a keyed fingerprint of it.
- Privacy: the privacy notice is now version 2026-10-30.2. It adds that an assistant able to act in your browser can see what you open there. Recording pauses until you accept it.
- You do: after updating, accept the privacy notice; Claude reads it to you and asks.
- Privacy: records uploaded before 0.11.2 keep their plain fingerprints, since the ledger never rewrites a record. Fingerprints follow the master key, so after `stair-dev rl key rotate` new records no longer match older ones.
- After an update, the first session shows what the previous version left to say, such as a changed privacy notice, instead of skipping it.
- On Linux the viewer opens a browser only when you run it yourself; run by an assistant, it says to run it in your own terminal.
- `stair-dev rl status` calls the SDK's own version number `sdk_package_version`, beside the pin that chose it (`sdk`).

## 0.12.0

The viewer works by grants: each view is a limited, recorded authorization, and your master key stays on your machine.

- Privacy: `stair-dev rl viewer` no longer puts your master key in the link. It grants a view of your sessions of the last seven days for an hour (`--days`, `--hours`): their keys are wrapped again here under a fresh key that only the link carries, and the grant is recorded in your ledger. When it ends, the ledger drops those keys and the link opens nothing.
- Privacy: Claude is never shown the link's key. The plugin opens the link in your browser, or prints it only in a terminal of your own; when Claude Code runs on another machine, run `stair-dev rl viewer` in a terminal there.
- Privacy: the privacy notice is now version 2026-10-30.1, describing the viewer as it now works. Recording pauses until you accept it.
- You do: after updating, accept the privacy notice; Claude reads it to you and asks.
- `stair-dev rl grants` lists your grants; `stair-dev rl revoke <grant>` ends one now.

## 0.11.2

Notices no longer speak to Claude, fingerprints can no longer be guessed, and the privacy notice says how things work today.

- Privacy: the fingerprints that let records be matched without carrying text (the prompt that opened a turn, a task handed to another session, a file write, a thinking block) are computed with a key derived from yours, so nobody can test guesses against them.
- Privacy: the words of the makers' notices are shown to you only. Claude is told only that there is a new version or a changed notice, and reads a new version's notes when you ask what it changes.
- Privacy: the privacy notice is now version 2026-10-30. It describes the two changes above, says that the name you give this machine is readable on the ledger, and says plainly how the viewer works today. Recording pauses until you accept it.
- You do: after updating, accept the new privacy notice; Claude reads it to you and asks.
- A notice left by the version you updated from is no longer shown after the update.
- Uploads wait longer for a slow ledger and go in smaller batches, so they no longer time out.

## 0.11.1

Updating is one step now: the plugin, the `stair` command and the plugin's Python environment move to the new version together.

- The `stair` command runs whichever version Claude Code has installed, so it no longer stays on an old one after an update. A command set up by an earlier version is switched over at the start of your next session.
- When a version needs a newer ledger SDK, the plugin builds a fresh Python environment for it in the background, once, and removes the old one.
- On macOS, recording now reaches the ledger: before, the upload after each turn did not start there, and the queued events could not be read. What waited on the machine is uploaded after your next turn.
- The update notice says what changed, and Claude can tell you more when you ask.

## 0.11.0

Each turn records who started it: you, another session, a background task or a notice from the app. Sessions started from other sessions, forks and sub-agents are linked to where they came from.

- A conversation forked in the app no longer uploads again the history it copied from the original.

## 0.10.1

The update notice refreshes the marketplace first, so the update finds the new version.

## 0.10.0

Accounts can be anonymous: no e-mail is needed to start, and `stair-dev rl claim you@example.com` adds one later.

- At the start of a session the plugin tells you when a new version or a changed privacy notice is out.
