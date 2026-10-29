# What Stair records, and who can see it

Notice version `2026-10-29`. Setup asks you to accept this version; the plugin records that you did.

## What is recorded

Every turn of every Claude Code session on this machine, from the transcript Claude Code writes, becomes records in a Reasoning Ledger account that is yours:

- each prompt you type, and the final answer;
- each tool call: the tool's name, what it was given, what it returned, how long it took, whether it succeeded;
- questions Claude asked you and your answers; permission prompts and what you did with them;
- sub-agents Claude started and what they were asked;
- plan steps, and writes to memory files, CLAUDE.md, skills and settings;
- thinking blocks, as a fingerprint only (size and hash); their text never leaves this machine;
- file writes, as a pointer (path and hash); the file's content never leaves this machine.

The hooks do not read anything else on this machine. Nothing is asked of the model: it does not know it is being recorded and is not asked to record anything.

## Where it goes, and what the ledger can see

Records go to one place: the ledger endpoint you give at setup (the hosted ledger `api.stair-ai.com`, run by Stair AI, unless you point it elsewhere). Before upload, the text of each record is encrypted on this machine with a key that is made here and stays here (`~/.stair/master.key`). The ledger stores the ciphertext and a wrapped per-session key it cannot open.

So the ledger, and the people who run it, can see the **structure** of your work: that a prompt came in, which tools were called in what order, how long they took, whether they succeeded, token counts, timestamps, the names of tools and the paths of files that were written. They **cannot** see the text: not your prompts, not the answers, not what tools were given or returned, not what was asked or delegated.

If a file path or a tool name is itself something you must not share (a client's repository, say), keep the plugin off that machine.

## What you can do

- Look at your own records, decrypted in your browser: `stair rl viewer`. The link carries your key after `#`; the browser never sends it to the server.
- Rotate your key: `stair rl key rotate`.
- Stop recording: uninstall the plugin (`claude plugin uninstall stair@stair-ai`), or delete `~/.stair/config.json`. Records already uploaded stay in your account.
- Ask for your account and its records to be deleted: write to colin@stair-ai.com. In this alpha there is no self-service deletion.

## What is not there yet

- Nobody can be given access to your records: not another person, not an evaluator. The design exists; the commands do not. Your account is yours alone.
- There is no backup command. Copy `~/.stair/master.key` yourself; without it, the content cannot be read, by anyone.
- This is an alpha. Records are kept, but the service may change or be reset; you will be told before anything is deleted.

## Who runs it

The hosted ledger is run by Stair AI. Its server software is open source (`StairAI/Reasoning-Ledger`), so what it does with your records can be read; this plugin's code is in the plugin directory on your machine, and you can read it or have Claude read it before you continue.
