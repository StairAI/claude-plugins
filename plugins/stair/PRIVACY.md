# What Stair records, and who can see it

Notice version `2026-10-29`. Setup asks you to accept this version; the plugin records that you did.

## What is recorded

Every turn of every Claude Code session on this machine, from the transcript Claude Code writes, becomes records in a Reasoning Ledger account that is yours:

- each prompt you type, and the final answer;
- each tool call: the tool's name, what it was given, what it returned, how long it took, whether it succeeded;
- questions Claude asked you and your answers; permission prompts and what you did with them;
- sub-agents Claude started and what they were asked;
- plans (how many steps, how long each; the words of the plan are content, below) and writes to memory files, CLAUDE.md, skills and settings;
- thinking blocks, as a fingerprint only (size and hash); their text never leaves this machine;
- file writes, as a pointer (path and hash), carried as content; the file's content never leaves this machine.

The hooks do not read anything else on this machine. Nothing is asked of the model: it does not know it is being recorded and is not asked to record anything.

## Where it goes, and what the ledger can see

Records go to one place: the ledger endpoint you give at setup (the hosted ledger `api.stair-ai.com`, run by Stair AI, unless you point it elsewhere). Before upload, the text of each record is encrypted on this machine with a key that is made here and stays here (`~/.stair/master.key`). The ledger stores the ciphertext and a wrapped per-session key it cannot open.

So the ledger, and the people who run it, can see the **structure** of your work: that a prompt came in, which tools were called in what order, how long they took, whether they succeeded, token counts, timestamps, the names of tools, how many characters each text had, how many steps a plan had, what kind of question or permission was raised, the class of an error, the type of a sub-agent. They **cannot** see the words: not your prompts, not the answers, not what tools were given or returned, not what was asked, the options offered or what was delegated, not the wording of a plan or a verdict, not file paths or memory targets (those are pointers, carried as content). The plugin's tests check that no word of a session appears outside the encrypted positions.

If a tool's name is itself something you must not share, or the shape of your work is, keep the plugin off that machine.

## Who you are to the ledger

Nobody, unless you say so. The account is anonymous: two keys made on this machine are its identity, and the ledger holds no e-mail for it unless you attach one (`stair rl claim you@example.com`), which you may do at any time or never. An attached e-mail lets you find the account again and, later, recover it; it is never used for anything else.

## What you can do

- Look at your own records, decrypted in your browser: `stair rl viewer`. The link carries your key after `#`; the browser never sends it to the server.
- Rotate your key: `stair rl key rotate`.
- Stop recording: uninstall the plugin (`claude plugin uninstall stair@stair-ai`), or delete `~/.stair/config.json`. Records already uploaded stay in your account.
- Ask for your account and its records to be deleted: write to colin@stair-ai.com with the `agent_id` that `stair rl status` prints (an anonymous account has nothing else to name it by). In this alpha there is no self-service deletion.
- Hear from the makers: at the start of a session the plugin may show one line, a new version or a changed notice, taken from a public file it checks hourly. A changed privacy notice pauses recording until you accept the new one; nothing leaves this machine in the meantime.

## What is not there yet

- Nobody can be given access to your records: not another person, not an evaluator. The design exists; the commands do not. Your account is yours alone.
- There is no backup command. Copy `~/.stair/master.key` yourself; without it, the content cannot be read, by anyone.
- This is an alpha. Records are kept, but the service may change or be reset; you will be told before anything is deleted.

## Who runs it

The hosted ledger is run by Stair AI. Its server software is open source (`StairAI/Reasoning-Ledger`), so what it does with your records can be read; this plugin's code is in the plugin directory on your machine, and you can read it or have Claude read it before you continue.
