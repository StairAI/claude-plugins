# Changes

What each version of the Stair plugin for Claude Code changes for the person using it, newest first. When a newer version is out, the plugin says so at the start of a session together with the entries between your version and the new one, and Claude tells you more when you ask. A line that starts with "You do:" is something you have to do; it is said first.

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

Accounts can be anonymous: no e-mail is needed to start, and `stair rl claim you@example.com` adds one later.

- At the start of a session the plugin tells you when a new version or a changed privacy notice is out.
