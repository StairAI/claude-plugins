# Stair for Claude Code

Keeps a record of your Claude Code sessions in a Reasoning Ledger you own: tool calls, questions and answers, decisions, outcomes. The text is encrypted on your machine with a key only you hold; the ledger sees the shape of the work, not its words. Alpha, by invitation.

## Install

Open a Claude Code session and say:

> Install Stair for me: follow https://raw.githubusercontent.com/StairAI/claude-plugins/main/INSTALL.md. My invite code is STAIR-XXXXX-XXXXX.

Claude installs the plugin, reads its code and tells you what it does, explains the privacy notice, asks for your consent, and only then sets it up. By hand instead:

```bash
claude plugin marketplace add StairAI/claude-plugins
claude plugin install stair@stair-ai
```

then `/stair:install STAIR-XXXXX-XXXXX` in a session, or see [`plugins/stair/README.md`](./plugins/stair/README.md).

The privacy notice is [`plugins/stair/PRIVACY.md`](./plugins/stair/PRIVACY.md). The plugin's source is `StairAI/Reasoning-Ledger-Integrations`; the ledger server is open source at `StairAI/Reasoning-Ledger`.
