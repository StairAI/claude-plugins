# Stair's privacy notice

Notice version `2026-10-31`. You accept a version at setup; the plugin keeps a note of which one, and asks again when it changes.

## In short

Stair keeps a record of your Claude Code sessions in an account that is yours, so you can look back at how your agent worked.

- Which sessions: every session on this machine. You can leave a project out.
- Our server sees the shape of the work: for example, that Bash ran four times, and for how long.
- It can't see the words. Prompts, answers, commands, code and file paths are encrypted on this machine, with a key that stays here.
- No sign-up, no e-mail.
- Any time: view your records, stop by uninstalling, or ask us to delete them.

Stair AI runs the server.

## Questions and answers

### Why does Stair keep this record?

So that you can look back at how your agent worked: what it was asked, what it did, and how it turned out. That is all it is for today. Before it is used for anything else, such as sharing, this notice changes and you are asked again.

### What is recorded?

Each turn of each session, from the transcript Claude Code writes: your prompt and the final answer; each tool call, what it was given and returned, how long it took, whether it worked; questions Claude asked and your answers; permission prompts and your choice; sub-agents and their tasks; plans; and writes to memory files, CLAUDE.md, skills and settings. Of a thinking block only its size and a fingerprint go, and of a file Claude writes only its path and a fingerprint, encrypted.

The plugin reads nothing else but its own files and this machine's system id, which tells your machines apart and reaches the server only as a hash. Nothing is asked of the model: the record is made from the transcript alone.

### What does the server see, and what not?

The shape of the work: who opened each turn (you, another session, a scheduled task); which tools ran, in what order, for how long, and whether they worked; the model, token counts and times; how long each text was; the kind of a question, a permission prompt or an error; and this machine's name in your account.

Not the words: prompts, answers, what tools were given and returned, file paths, the wording of plans and questions. They are encrypted on this machine with a key made here that stays here (`~/.stair/master.key`); the server keeps the encrypted text and, per session, a locked copy of its key that only yours opens. The plugin's tests check that no word of a session lands outside the encrypted parts.

Two details. A record that has to tell texts apart carries a fingerprint made with a key derived from yours, which tells anyone without your key nothing. And each encrypted text carries its size and a plain SHA-256 digest, which your viewer checks it against: that hides a long text, but a very short or common one, a one-word reply say, can be confirmed by someone who guesses it, and identical texts show identical digests.

### What if the shape of my work is sensitive too?

Leave that project out: `stair rl exclude <folder>` (Claude can run it for you). Sessions that work in that folder or below it are not recorded from then on, and a session that moves into it stops being recorded there. `stair rl include <folder>` records new sessions there again. What was sent before stays until you ask for it to be deleted.

### Can I see what is sent, before it is sent?

Yes: `stair rl preview` shows the last turn of a session as the server would get it, the readable shape beside the encrypted parts, and sends nothing.

### Who am I to the server?

An account with no name or e-mail: two keys made on this machine are its identity. You can attach an e-mail any time with `stair rl claim you@example.com`; it is used only to find the account again. This machine's name in your account (`claude-code-mac`, say, unless you pick one) is readable on the server.

### What can I do, and how?

- View your records, decrypted in your browser: `stair rl viewer` opens an hour's view of your last seven days on this machine, or prints the link in your own terminal, and notes the view in your account (`stair rl grants` lists views, `stair rl revoke` ends one). Whoever has the link can read those sessions while it lasts, and so can an assistant that operates your browser: keep it to yourself.
- Leave a project out: `stair rl exclude <folder>`.
- Stop: uninstall the plugin (`claude plugin uninstall stair@stair-ai`). Your keys stay in `~/.stair`, so installing again picks up the same account; delete that folder to forget it.
- Have your account and records deleted: write to colin@stair-ai.com with the `agent_id` that `stair rl status` shows. In this alpha we do it for you.
- Make a new content key: `stair rl key rotate`.

### What do I need to keep safe?

The two key files in `~/.stair`, `owner.key` and `master.key`, are your account: keep a copy somewhere safe. Without `master.key` your records can't be read, by you or anyone; with both, a reinstall or another machine gets the account back (`stair rl setup --restore <folder>`).

### Will the plugin tell me things?

At the start of a session it can show you one line from its makers, about a new version or a change to this notice, from a public file it checks at most hourly. You see their words; Claude learns only that there is news, not the words. When this notice changes, nothing is sent until you read and accept the new version by typing `/stair:notice`; sessions in the meantime wait on this machine, and you choose whether they are sent.

### What isn't there yet?

- Sharing: there is no way yet to give someone else, a person or an evaluator, access to your records.
- A backup command: copy the two key files yourself.
- Permanence: this is an alpha. The service can change or be reset; you will be told before anything is deleted.

### Who runs it?

Stair AI runs the server your records go to, `api.stair-ai.com` (the team's staging channel uses `stg-api.stair-ai.com`). Its software is open source (`StairAI/Reasoning-Ledger`), and this plugin's code is in its folder on your machine, for you or Claude to read.

## Changes to this notice

- `2026-10-31`: rewritten as questions and answers with a short version first. New: why Stair keeps the record, leaving a project out, a preview of what is sent, choosing whether sessions that waited for a changed notice are sent, and the digest each encrypted text carries. What is recorded and sent is unchanged.
- `2026-10-30.2`: fingerprints keyed with your key; the makers' notices no longer reach Claude; the viewer opens a limited, noted view instead of carrying your master key.
