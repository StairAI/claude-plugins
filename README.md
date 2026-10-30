# Stair for Claude Code: staging channel

This branch is the staging channel of Stair. Every new version of the plugin lands here first, records to the staging ledger (`stg-api.stair-ai.com`), and is tried by the Stair team before the same plugin is released on [`main`](https://github.com/StairAI/claude-plugins). If you are not on the team, install from `main`.

## Install

The staging plugin is `stair-dev`. It installs side by side with the release plugin `stair`: its state is in `~/.stair-dev`, its command is `stair-dev`, and with both installed every turn is recorded twice, each copy into its own ledger.

```bash
claude plugin marketplace add StairAI/claude-plugins#staging
claude plugin install stair-dev@stair-ai-dev
```

Then, in a new session, run `/stair-dev:install STAIR-XXXXX-XXXXX` with an invite code for the staging ledger; the team has them.

## Update

At the start of a session the plugin says when a newer staging version is out; say "update stair". By hand:

```bash
claude plugin marketplace update stair-ai-dev && claude plugin update stair-dev@stair-ai-dev
```

The first command fetches this branch; the new version applies to sessions started after the update.
