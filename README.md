# Stair for Claude Code

Keep your AI sessions in a ledger only you hold the key to.

Stair for Claude Code keeps a record of each session you run, in a ledger you own and hold the key to. You can open your record at any time. You will choose what to share, and what you share will become consumer intelligence for brands, research teams and funds; you will be paid as it is used.

By default, Claude Code deletes session transcripts from your machine after 30 days ([`cleanupPeriodDays`](https://code.claude.com/docs/en/settings-reference#cleanupperioddays); sessions from the Claude desktop app are kept longer). Stair keeps your record.

The text is encrypted on your machine with a key only you hold; the ledger sees the shape of the work, not its words. Alpha, by invitation.

## Install

Open a Claude Code session and say:

> Install Stair for me: follow https://raw.githubusercontent.com/StairAI/claude-plugins/main/INSTALL.md. My invite code is STAIR-XXXXX-XXXXX.

Claude installs the plugin, reads its code and tells you in three lines what it found, shows you the privacy notice in short and asks one question; only after your yes does it set up. By hand instead:

```bash
claude plugin marketplace add StairAI/claude-plugins
claude plugin install stair@stair-ai
```

then `/stair:install STAIR-XXXXX-XXXXX` in a session, or see [`plugins/stair/README.md`](./plugins/stair/README.md).

## Update

From 0.10.0 on, the plugin tells you at the start of a session when a newer version is out; say "update stair". By hand, or from an earlier version:

```bash
claude plugin marketplace update stair-ai && claude plugin update stair@stair-ai
```

The first command fetches the marketplace (without it, the second finds nothing newer). The new version applies to sessions started after the update; a session already open switches over when you type `/reload-plugins` in it, which Claude asks you to do. Your account and keys in `~/.stair` stay as they are.

## Uninstall and install again

`claude plugin uninstall stair@stair-ai` stops recording and leaves your account's keys in `~/.stair`. Installing again picks them up, and recording resumes from the next session: the same account, the same records, no invite code. If you deleted `~/.stair` but kept `owner.key` and `master.key`, say where they are when Claude installs Stair (the folder, never the keys themselves): setup restores the same account from that folder (`stair rl setup --restore <folder>`).

## Your choices

`stair rl exclude <folder>` leaves a project out: sessions that work there are not recorded. `stair rl preview` shows what would be sent for your last turn, and sends nothing. When the privacy notice changes, nothing is sent until you type `/stair:notice` and accept it.

The privacy notice is [`plugins/stair/PRIVACY.md`](./plugins/stair/PRIVACY.md). The plugin's source is `StairAI/Reasoning-Ledger-Integrations`; the ledger server is open source at `StairAI/Reasoning-Ledger`.
