#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stair (batch design): the Stair plugin for Claude Code, which writes schema 0.5 records to a Reasoning Ledger.

The hooks do almost nothing on the critical path: `bin/stair` appends the hook's JSON to a local queue in plain bash and,
on Stop / SessionEnd, starts this program detached. This program then:
  * reads the queue (Stop, SessionEnd, PermissionRequest, PermissionDenied, SubagentStop events),
  * maps each affected transcript with mapper.py (the transcript is the source of truth),
  * uploads the records that have not been uploaded yet, in batches, through the Python SDK,
  * remembers what was uploaded per transcript.

Commands: process (drain the queue), setup, status, flush (retry the spool), map (dry run: map a transcript), viewer (a one-time sign-in link to the viewer; the key stays in its file), key (the content master key: rotate), admin (invite codes, with the ledger's administrator token). Nothing is asked of the model: every record comes from the transcript and the hook events.

Content is encrypted on this machine before upload (the SDK's ContentEncryption): setup makes a master key, kept in master.key and never sent; the ledger holds ciphertext and wrapped per-session keys. The viewer link carries the master key in its fragment, which the browser keeps to itself.
State under $STAIR_HOME (default ~/.stair): config.json, owner.key, master.key, queue/events.jsonl, state/<transcript>.json, spool.jsonl, logs/.
"""
from __future__ import annotations
import json, os, sys, time, uuid, hashlib, argparse, socket, getpass, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mapper import Mapper, strip_none  # noqa: E402

def plugin_name():
    """This copy's name from plugin.json: `stair` (the release channel) or `stair-dev` (the source repository)."""
    try: return json.load(open(HERE / ".claude-plugin" / "plugin.json", encoding="utf-8")).get("name") or "stair"
    except Exception: return "stair"

def channel():
    """The channel's defaults from channel.env beside this file: which ledger and which SDK, unless overridden."""
    import shlex
    out = {"STAIR_CHANNEL": "dev", "STAIR_DEFAULT_ENDPOINT": "https://stg-api.stair-ai.com"}
    try:
        for line in open(HERE / "channel.env", encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); out[k.strip()] = " ".join(shlex.split(v))
    except Exception: pass
    return out

NAME = plugin_name()
CHANNEL = channel()
# Each channel keeps its state under ~/.<name>: ~/.stair for the release channel, ~/.stair-dev for the source.
HOME = Path(os.environ.get("STAIR_HOME") or os.environ.get("RL_PLUGIN_HOME") or Path.home() / ("." + NAME))
QUEUE = HOME / "queue" / "events.jsonl"
BATCH = 50
# The privacy notice (PRIVACY.md beside this file) a person accepts at setup. Bumped whenever the notice changes in
# substance; setup then asks again.
PRIVACY_NOTICE_VERSION = "2026-10-29"

def plugin_version():
    try: return json.load(open(HERE / ".claude-plugin" / "plugin.json", encoding="utf-8")).get("version") or "0"
    except Exception: return "0"

# urllib's default User-Agent (Python-urllib/x.y) is refused by the browser-integrity check of the CDN in front of the hosted
# ledger (Cloudflare error 1010), so the two direct requests below name the plugin instead. The SDK (httpx) names itself.
USER_AGENT = NAME + "/" + plugin_version()

def now_ms(): return int(time.time() * 1000)
def log(where, err):
    try:
        (HOME / "logs").mkdir(parents=True, exist_ok=True)
        with open(HOME / "logs" / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now_ms(), "where": where, "error": repr(err)[:400]}) + "\n")
    except Exception:
        pass

def load_config():
    p = HOME / "config.json"
    if not p.exists(): return None
    try: return json.load(open(p, encoding="utf-8"))
    except Exception as e: log("config", e); return None

def api_key(cfg):
    if cfg.get("api_key_file"): return open(os.path.expanduser(cfg["api_key_file"]), encoding="utf-8").read().strip()
    return os.environ.get("STAIR_API_KEY") or os.environ.get("RL_API_KEY", "")

def device_info():
    mid = ""
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try: mid = open(p).read().strip(); break
        except Exception: pass
    host = socket.gethostname()
    return {"device_id": hashlib.sha256((mid or host).encode()).hexdigest()[:32], "host": host, "user": getpass.getuser()}

def master_key_path(cfg):
    """Where the content master key lives, or None when this install uploads in the clear."""
    p = cfg.get("master_key_file")
    return Path(os.path.expanduser(p)) if p else None

def encryption_for(cfg):
    """The SDK's ContentEncryption for this install, or None when it uploads in the clear."""
    p = master_key_path(cfg)
    if p is None: return None
    from reasoning_ledger import ContentEncryption, load_master_key
    return ContentEncryption(master_key=load_master_key(p), agent_id=cfg.get("agent_id"))

_client = None
def client(cfg):
    global _client
    if _client is None:
        sys.path.insert(0, cfg["sdk_src"])
        from reasoning_ledger import LedgerClient, LedgerClientConfig
        _client = LedgerClient(LedgerClientConfig(api_key=api_key(cfg), agent_id=cfg["agent_id"], endpoint=cfg["endpoint"], encryption=encryption_for(cfg)))
    return _client

def upload(cfg, records):
    """Upload records in batches; the SDK uploads raw content at content positions first. Returns (ok_ids, failed).
    A batch answers per record (the server isolates failures inside a batch), so a record counts as uploaded only when its
    own acknowledgement came back without an error code. A record whose upstream failed in this run is not sent at all:
    the server would reject it for the missing upstream. It goes to the spool with that reason, and `stair rl flush` retries it
    once the upstream is in."""
    c = client(cfg); ok = []; failed = []; bad = set()
    def fail(r, err):
        failed.append({"record": r, "error": str(err)[:300]}); bad.add(r["record_id"])
    for i in range(0, len(records), BATCH):
        chunk = []
        for r in records[i:i + BATCH]:
            blocked = [u for u in (r.get("upstream_record_id") or []) if u in bad]
            if blocked: fail(r, f"upstream_failed: {blocked[0]}")
            else: chunk.append(r)
        attest = [r for r in chunk if r["behavior"] == "Attesting"]; others = [r for r in chunk if r["behavior"] != "Attesting"]
        if others:
            try:
                ack = c._submit_batch(others)
                results = [x for x in (ack.get("results") or []) if isinstance(x, dict)] if isinstance(ack, dict) else []
                by_id = {x.get("record_id"): x for x in results}
                for n, r in enumerate(others):
                    res = by_id.get(r["record_id"]) or (results[n] if n < len(results) and not results[n].get("record_id") else None)
                    if res is None: fail(r, "no_ack: the batch response did not mention this record")
                    elif res.get("code"): fail(r, f"{res['code']}: {res.get('message', '')}")
                    else: ok.append(r["record_id"])
            except Exception as e:
                log("upload", e)
                for r in others:   # one by one, so a single bad record does not block the rest
                    try: c._submit(r); ok.append(r["record_id"])
                    except Exception as e2: fail(r, repr(e2))
        for a in attest:
            try: c._submit_attesting(a); ok.append(a["record_id"])
            except Exception as e2: fail(a, repr(e2))
    return ok, failed

# ---------------------------------------------------------------- state per transcript
def state_path(transcript): return HOME / "state" / (hashlib.sha256(str(transcript).encode()).hexdigest()[:24] + ".json")
def load_state(transcript):
    p = state_path(transcript)
    if p.exists():
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return {"transcript": str(transcript), "uploaded": [], "permissions": [], "subagents": [], "notes": [], "last_processed": None}
def save_state(st):
    p = state_path(st["transcript"]); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False); os.replace(tmp, p)

def process_transcript(cfg, transcript, payload, st, dry=False):
    """Map the whole transcript, upload what is new, remember it."""
    conv = payload.get("session_id") or Path(transcript).stem
    mp = Mapper(cfg["agent_id"], cfg.get("device") or device_info(), thinking_text=cfg.get("thinking_text", "hash"))
    records, info = mp.map_transcript(transcript, conv, permission_events=[dict(p) for p in st.get("permissions", [])])
    # Sub-agent transcripts: their own sessions under the same conversation. The Agent call's result names the
    # sub-agent's id, so the mapper already set child_session_id on its Delegating; a call whose result did not is
    # matched by order (the n-th unmatched spawn answers the n-th sub-agent that stopped without a match).
    spawned = {r["child_session_id"]: r["record_id"] for r in records if r.get("behavior") == "Delegating" and r.get("child_session_id")}
    unmatched = [r for r in records if r.get("behavior") == "Delegating" and r.get("kind") == "spawn" and not r.get("child_session_id")
                 and r.get("delegate_agent_id") != "claude-code-session"]
    for sa in sorted(st.get("subagents", []), key=lambda x: x.get("ts") or 0):
        atp = sa.get("agent_transcript_path"); prefix = "%s:sub:%s" % (conv, str(sa.get("agent_id") or "x")[:8])
        parent_ref = spawned.get(prefix)
        if not parent_ref and unmatched:
            rec = unmatched.pop(0); rec["child_session_id"] = prefix; parent_ref = rec["record_id"]
        if atp and os.path.exists(atp):
            try:
                child, _ = mp.map_transcript(atp, conv, child_prefix=prefix, parent_ref=parent_ref)
                records.extend(child)
            except Exception as e:
                log("subagent-map", e)
    records = [strip_none(r) for r in records]
    done = set(st.get("uploaded", [])); new = [r for r in records if r["record_id"] not in done]
    if dry: return records, new, info
    ok, failed = upload(cfg, new) if new else ([], [])
    st["uploaded"] = sorted(done | set(ok)); st["last_processed"] = now_ms(); st["info"] = info; save_state(st)
    if failed:
        HOME.mkdir(parents=True, exist_ok=True)
        with open(HOME / "spool.jsonl", "a", encoding="utf-8") as f:
            for x in failed: f.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
    return records, new, {**info, "uploaded": len(ok), "failed": len(failed)}

def process(args):
    cfg = load_config()
    if not cfg: return 0
    paused = uploads_paused(cfg, fetch_notices(cfg))
    if paused:   # the queue keeps growing; nothing leaves this machine until the new notice is accepted
        log("paused", "privacy notice %s not accepted yet" % paused.get("privacy_notice_version")); refresh_notices(cfg); return 0
    if not QUEUE.exists(): refresh_notices(cfg); return 0
    time.sleep(args.delay)   # the transcript is written asynchronously and may lag the Stop hook by a moment
    lines = [l for l in open(QUEUE, encoding="utf-8") if l.strip()]
    open(QUEUE, "w").close()
    by_transcript = {}; acts = {}
    for l in lines:
        try: ev = json.loads(l)
        except Exception: continue
        p = ev.get("payload") or {}; tp = p.get("transcript_path"); e = ev.get("event")
        if not tp: continue
        st = by_transcript.setdefault(tp, load_state(tp))
        if e in ("PermissionRequest", "PermissionDenied"):
            st.setdefault("permissions", []).append({"tool_name": p.get("tool_name"), "tool_use_id": p.get("tool_use_id"), "tool_input": p.get("tool_input"), "ts": ev.get("ts"), "denied": e == "PermissionDenied"})
        elif e == "SubagentStop":
            st.setdefault("subagents", []).append({"agent_id": p.get("agent_id"), "agent_type": p.get("agent_type"), "agent_transcript_path": p.get("agent_transcript_path"), "ts": ev.get("ts")})
        if e in ("Stop", "SessionEnd"): acts[tp] = p
    summary = []
    for tp, st in by_transcript.items():
        if tp not in acts:
            save_state(st); continue
        try:
            _, new, info = process_transcript(cfg, tp, acts[tp], st)
            summary.append({"transcript": tp, "new": len(new), **info})
        except Exception as e:
            log("process", e); save_state(st)
    if summary: print(json.dumps(summary, ensure_ascii=False))
    refresh_notices(cfg)
    return 0


def register_owner(endpoint, email, token=None, invite=None):
    """Create an owner on the ledger and return its API key, which the server shows exactly once. Self-service where the
    instance allows it (RL_REGISTRATION=open, or =invite with an invite code); elsewhere the instance's registration token
    goes in X-Admin-Token."""
    import urllib.request, urllib.error
    fields = {"wallet_mode": "custodial"}
    if email: fields["email"] = email          # optional: without it the owner is anonymous, its keys its identity
    if invite: fields["invite_code"] = invite.strip()
    body = json.dumps(fields).encode("utf-8")
    headers = {"content-type": "application/json", "user-agent": USER_AGENT}
    if token: headers["x-admin-token"] = token
    req = urllib.request.Request(endpoint.rstrip("/") + "/v1/owners", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as res: r = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        try: detail = json.loads(detail).get("message") or detail
        except Exception: pass
        hint = " (pass --invite <code>)" if e.code == 403 and "invite" in detail.lower() and not invite else ""
        if e.code == 400 and "email" in detail.lower() and not email: hint = " (this ledger still asks for an e-mail: add --register you@example.com)"
        raise SystemExit("stair: registration refused (%d): %s%s" % (e.code, detail, hint))
    key = r.get("api_key")
    if not key: raise SystemExit("stair: the ledger already has an owner with this e-mail and did not return its key; use --api-key-file with the key you were given")
    return key

def save_key(path, key):
    """The owner key goes into a file only this user can read; it is never printed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(key.strip() + "\n")

def ensure_master_key(path):
    """The content master key: made once, kept in a file only this user can read, never printed or sent. Returns its id."""
    from reasoning_ledger import generate_master_key, load_master_key, master_key_id, save_master_key
    if not path.exists(): save_master_key(path, generate_master_key())
    return master_key_id(load_master_key(path))

def privacy_notice_text():
    try: return open(HERE / "PRIVACY.md", encoding="utf-8").read()
    except Exception: return "(PRIVACY.md is missing from the plugin directory)"

def require_privacy_consent(args):
    """Setup goes no further until the current notice has been accepted: whoever runs it, a person or an assistant
    acting for one, has to have put the notice in front of the person first. The notice is printed here so that it is
    at least seen; accepting is the flag."""
    given = getattr(args, "accept_privacy_notice", None)
    if given == PRIVACY_NOTICE_VERSION: return
    sys.stdout.write(privacy_notice_text().rstrip() + "\n\n")
    if given: print("stair: the privacy notice changed (you accepted %s; the current notice is %s). Read it above, then run setup again with --accept-privacy-notice %s" % (given, PRIVACY_NOTICE_VERSION, PRIVACY_NOTICE_VERSION))
    else: print("stair: read the notice above (PRIVACY.md in the plugin directory); then run setup again with --accept-privacy-notice %s. Nothing was registered or sent." % PRIVACY_NOTICE_VERSION)
    raise SystemExit(2)

def setup(args):
    require_privacy_consent(args)
    HOME.mkdir(parents=True, exist_ok=True)
    previous = load_config() or {}
    invite = getattr(args, "invite", None) or os.environ.get("STAIR_INVITE_CODE") or previous.get("invite_code")
    key_path = HOME / "owner.key"; email = (getattr(args, "register", None) or "").strip() or None
    if getattr(args, "register", None) is None and args.api_key_file:
        pass                                       # a key the person was given
    elif getattr(args, "register", None) is not None or not key_path.exists():
        # Register: anonymously unless an e-mail is given (--register you@example.com). The keys are the identity; an
        # e-mail can be claimed later with `stair rl claim`.
        token = os.environ.get("STAIR_REGISTRATION_TOKEN") or os.environ.get("RL_REGISTRATION_TOKEN") or (open(os.path.expanduser(args.registration_token_file), encoding="utf-8").read().strip() if args.registration_token_file else None)
        if key_path.exists() and not args.force:
            raise SystemExit("stair: %s exists; leave out --register to keep using it, --api-key-file %s to say so, or --force to replace it" % (key_path, key_path))
        save_key(key_path, register_owner(args.endpoint, email, token, invite)); args.api_key_file = str(key_path)
    else:
        args.api_key_file = str(key_path)          # set up again on a machine that already has its owner key
    cfg = {"endpoint": args.endpoint.rstrip("/"), "api_key_file": args.api_key_file, "agent_name": args.agent_name, "sdk_src": args.sdk_src, "device": device_info(),
           "privacy_notice": {"version": PRIVACY_NOTICE_VERSION, "accepted_at": now_ms()}}
    if email: cfg["owner_email"] = email
    elif previous.get("owner_email"): cfg["owner_email"] = previous["owner_email"]
    if invite: cfg["invite_code"] = invite.strip()   # kept, so a later setup on this machine does not ask for it again
    if getattr(args, "viewer_url", None): cfg["viewer_url"] = args.viewer_url.rstrip("/")
    sys.path.insert(0, cfg["sdk_src"])
    from reasoning_ledger import LedgerClient, RegisterAgentOpts, ResolveAgentOpts
    key = api_key(cfg)
    try: aid = LedgerClient.resolve_agent_id(ResolveAgentOpts(api_key=key, endpoint=cfg["endpoint"], name=cfg["agent_name"]))
    except Exception: aid = LedgerClient.register_agent(RegisterAgentOpts(api_key=key, endpoint=cfg["endpoint"], name=cfg["agent_name"]))["agent_id"]
    cfg["agent_id"] = aid
    master_id = None
    if not getattr(args, "plaintext", False):
        cfg["master_key_file"] = str(HOME / "master.key"); master_id = ensure_master_key(HOME / "master.key")
    json.dump(cfg, open(HOME / "config.json", "w", encoding="utf-8"), indent=1)
    probe = {"schema_version": "0.5", "agent_id": aid, "session_id": "stair:setup", "record_id": str(uuid.uuid4()), "behavior": "Other", "client_ts_utc": now_ms(),
             "executor": "det", "record_phase": "post_execution", "label": "stair.setup_probe",
             "data": {"endpoint": cfg["endpoint"], "device": cfg["device"]["device_id"], "privacy_notice": cfg["privacy_notice"], "plugin": plugin_version()},
             "written_by": {"component": "stair", "credential": "owner_api_key"}, "classification": {"source": "instrumented", "mapper": "stair@0.3", "confidence": 1.0}}
    ok, failed = upload(cfg, [probe])
    print(json.dumps({"ok": not failed, "agent_id": aid, "endpoint": cfg["endpoint"], "home": str(HOME), "device_id": cfg["device"]["device_id"],
                      "encryption": "on" if master_id else "off", "master_key_id": master_id, "master_key_file": cfg.get("master_key_file"),
                      "privacy_notice_accepted": PRIVACY_NOTICE_VERSION, "owner": cfg.get("owner_email") or "anonymous",
                      **({"error": failed[0]["error"]} if failed else {})}))
    return 0 if not failed else 1

def status(args):
    cfg = load_config(); q = sum(1 for _ in open(QUEUE, encoding="utf-8")) if QUEUE.exists() else 0
    sp = sum(1 for _ in open(HOME / "spool.jsonl", encoding="utf-8")) if (HOME / "spool.jsonl").exists() else 0
    states = list((HOME / "state").glob("*.json")) if (HOME / "state").exists() else []
    up = 0
    for s in states:
        try: up += len(json.load(open(s, encoding="utf-8")).get("uploaded", []))
        except Exception: pass
    enc = {"enabled": False}
    if cfg and master_key_path(cfg):
        try:
            from reasoning_ledger import load_master_key, master_key_id
            enc = {"enabled": True, "master_key_id": master_key_id(load_master_key(master_key_path(cfg))), "master_key_file": str(master_key_path(cfg))}
        except Exception as e:
            enc = {"enabled": True, "error": "master key unreadable: %s" % str(e)[:120], "master_key_file": str(master_key_path(cfg))}
    print(json.dumps({"ok": bool(cfg) and "error" not in enc, "configured": bool(cfg), "endpoint": cfg and cfg.get("endpoint"), "agent_id": cfg and cfg.get("agent_id"),
                      "transcripts": len(states), "records_uploaded": up, "queued_events": q, "spooled": sp, "home": str(HOME), "encryption": enc,
                      "privacy_notice": (cfg or {}).get("privacy_notice"), "owner": (cfg or {}).get("owner_email") or ("anonymous" if cfg else None),
                      "plugin": NAME + " " + plugin_version(), "channel": CHANNEL["STAIR_CHANNEL"], "notice_pending": NOTICE_PENDING.exists()}))
    return 0

def flush(args):
    cfg = load_config(); p = HOME / "spool.jsonl"
    if not cfg or not p.exists(): print(json.dumps({"ok": True, "flushed": 0})); return 0
    items = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    ok, failed = upload(cfg, [x["record"] for x in items])
    with open(p, "w", encoding="utf-8") as f:
        for x in failed: f.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"ok": not failed, "flushed": len(ok), "left": len(failed)})); return 0

def mint_ticket(cfg, next_path=None):
    """Ask the ledger for a one-time viewer sign-in link: POST /v1/viewer/tickets with the owner key (the key never leaves this
    process). The link works once and expires after the server's ticket lifetime (VIZ_TICKET_TTL_SECONDS, 60 s by default)."""
    import urllib.request
    body = json.dumps({"next": next_path} if next_path else {}).encode("utf-8")
    req = urllib.request.Request(cfg["endpoint"].rstrip("/") + "/v1/viewer/tickets", data=body, method="POST",
                                 headers={"content-type": "application/json", "x-api-key": api_key(cfg), "user-agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8"))

def viewer(args):
    """Print a one-time link that signs the browser into the viewer. The link is built from the viewer's public address
    (`viewer_url` in config.json, or --base; the upload endpoint otherwise) and the ticket the server issued."""
    cfg = load_config()
    if not cfg: print(json.dumps({"ok": False, "error": "not configured: run `stair rl setup` first"})); return 1
    if args.base and args.save:
        cfg["viewer_url"] = args.base.rstrip("/"); json.dump(cfg, open(HOME / "config.json", "w", encoding="utf-8"), indent=1)
    base = (args.base or cfg.get("viewer_url") or cfg["endpoint"]).rstrip("/")
    t = mint_ticket(cfg, args.next)
    url = base + t["ticket_url"]; secs = max(0, int((t["expires_at"] - now_ms()) / 1000))
    # The content master key rides in the fragment: the browser keeps it for the tab and never sends it, and the
    # viewer decrypts with it. The ticket is still what signs the browser in.
    carries_key = False
    if master_key_path(cfg) and not getattr(args, "no_key", False):
        from reasoning_ledger import load_master_key, master_key_fragment
        url += "#k=" + master_key_fragment(load_master_key(master_key_path(cfg))); carries_key = True
    if args.json: print(json.dumps({"ok": True, "url": url, "expires_in_s": secs, "one_time": True, "decrypts": carries_key}))
    else:
        print(url); print(f"one-time link, valid for {secs} s" + ("; it carries your content key, so share the link with nobody" if carries_key else ""))
    return 0

def owner_request(cfg, method, path, body=None):
    """A request to the ledger as this owner, outside the SDK (the few owner-account calls)."""
    import urllib.request, urllib.error
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg["endpoint"].rstrip("/") + path, data=data, method=method,
                                 headers={"content-type": "application/json", "x-api-key": api_key(cfg), "user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as res: return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        try: detail = json.loads(detail).get("message") or detail
        except Exception: pass
        raise SystemExit("stair: the ledger answered %d: %s" % (e.code, detail))

def claim(args):
    """`claim EMAIL`: give this anonymous owner an e-mail, so the account can be found again and, later, recovered."""
    cfg = load_config()
    if not cfg: print(json.dumps({"ok": False, "error": "not configured: run `stair rl setup` first"})); return 1
    r = owner_request(cfg, "PATCH", "/v1/owners/me", {"email": args.email.strip()})
    cfg["owner_email"] = r.get("email") or args.email.strip(); json.dump(cfg, open(HOME / "config.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps({"ok": True, "owner_id": r.get("owner_id"), "email": cfg["owner_email"]})); return 0

# ---------------------------------------------------------------- notices: what the plugin's makers want the person to know
NOTICES_FILE = HOME / "notices.json"              # what was fetched, when, and which notices were shown
NOTICE_PENDING = HOME / "notice.pending.json"      # the next SessionStart hook prints this and renames it
NOTICE_SHOWN = HOME / "notice.shown.json"
NOTICES_EVERY_MS = 60 * 60 * 1000

def version_tuple(v):
    try: return tuple(int(x) for x in str(v).split("-")[0].split("."))
    except Exception: return (0,)

def fetch_notices(cfg, force=False):
    """Fetch the channel's notices file (a public, static JSON beside the published plugin) at most hourly; never raises."""
    url = CHANNEL.get("STAIR_NOTICES_URL") or ""
    if not url: return None
    cache = {}
    try: cache = json.load(open(NOTICES_FILE, encoding="utf-8"))
    except Exception: pass
    if not force and now_ms() - (cache.get("fetched_at") or 0) < NOTICES_EVERY_MS: return cache
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as res: fetched = json.loads(res.read().decode("utf-8"))
        cache = {"fetched_at": now_ms(), "url": url, "notices": fetched.get("notices") or [], "latest_version": fetched.get("latest_version") or {},
                 "seen": cache.get("seen") or []}
        NOTICES_FILE.parent.mkdir(parents=True, exist_ok=True); json.dump(cache, open(NOTICES_FILE, "w", encoding="utf-8"), indent=1)
    except Exception as e:
        log("notices", e)
    return cache or None

def mark_shown():
    """The SessionStart hook renamed the pending file after printing it: record those notices as seen."""
    if not NOTICE_SHOWN.exists(): return
    try:
        shown = json.load(open(NOTICE_SHOWN, encoding="utf-8")); cache = json.load(open(NOTICES_FILE, encoding="utf-8"))
        cache["seen"] = sorted(set(cache.get("seen") or []) | set(shown.get("ids") or [])); json.dump(cache, open(NOTICES_FILE, "w", encoding="utf-8"), indent=1)
    except Exception as e: log("notices-shown", e)
    try: NOTICE_SHOWN.unlink()
    except Exception: pass

def pending_notices(cfg, cache):
    """Which notices apply to this install and were not shown yet: an update when the published version is newer, a
    privacy notice newer than the one accepted (uploads pause until it is), and plain messages."""
    if not cache: return []
    seen = set(cache.get("seen") or []); out = []
    latest = (cache.get("latest_version") or {}).get(NAME)
    installed = plugin_version()
    if latest and version_tuple(latest) > version_tuple(installed):
        out.append({"id": "update:%s" % latest, "kind": "update", "title": "%s %s is available (you have %s)" % (NAME, latest, installed)})
    accepted = ((cfg or {}).get("privacy_notice") or {}).get("version") or ""
    for n in cache.get("notices") or []:
        nid = n.get("id")
        if not nid or nid in seen: continue
        if n.get("until") and str(n["until"]) < time.strftime("%Y-%m-%d"): continue
        if n.get("channel") and n["channel"] != CHANNEL["STAIR_CHANNEL"]: continue
        if n.get("kind") == "privacy" and n.get("privacy_notice_version") and str(n["privacy_notice_version"]) <= accepted: continue
        out.append(n)
    return [n for n in out if n["id"] not in seen]

def uploads_paused(cfg, cache):
    """Uploads stop when the makers published a privacy notice newer than the one this person accepted."""
    accepted = ((cfg or {}).get("privacy_notice") or {}).get("version") or ""
    for n in (cache or {}).get("notices") or []:
        if n.get("kind") == "privacy" and n.get("privacy_notice_version") and str(n["privacy_notice_version"]) > accepted: return n
    return None

def render_pending(pending, paused):
    """What the SessionStart hook prints: a line for the person, and context for the assistant, who asks before acting."""
    if not pending and not paused: return None
    lines = []; ctx = ["Stair plugin (%s) notices for this machine. Tell the person in one or two lines; ask before running anything." % NAME]
    for n in pending:
        kind = n.get("kind"); title = n.get("title") or n.get("id"); text = n.get("text") or ""
        if kind == "update":
            lines.append("Stair: " + title + ". Say \"update stair\" to update.")
            mkt = "stair-ai-dev" if NAME == "stair-dev" else "stair-ai"
            # `claude plugin update` alone compares against the local copy of the marketplace, which is only refreshed by
            # `claude plugin marketplace update`; without it the update reports the installed version as the latest.
            ctx.append("Update available: %s. If they want it, run `claude plugin marketplace update %s && claude plugin update %s@%s` "
                       "(both, in this order: the first fetches the marketplace), then tell them the new version applies to sessions "
                       "started after the update." % (title, mkt, NAME, mkt))
        elif kind == "privacy":
            lines.append("Stair: the privacy notice changed (%s); recording is paused until you accept it." % n.get("privacy_notice_version"))
            ctx.append("Privacy notice changed to version %s: %s Uploads are paused until accepted. Update the plugin if the installed PRIVACY.md is older, read PRIVACY.md to the person in their language, ask for consent, and only with a clear yes run `%s rl accept-notice %s`." % (n.get("privacy_notice_version"), text, NAME, n.get("privacy_notice_version")))
        else:
            lines.append("Stair: " + title + (": " + text if text else ""))
            ctx.append("Message from the makers: %s %s" % (title, text))
    if paused and not any(n.get("kind") == "privacy" for n in pending):
        lines.append("Stair: recording is paused until the new privacy notice (%s) is accepted." % paused.get("privacy_notice_version"))
    return {"ids": [n["id"] for n in pending], "systemMessage": " ".join(lines),
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(ctx)}}

def refresh_notices(cfg, force=False):
    """After an upload run: record what was shown, fetch, and leave what should be said next for the SessionStart hook."""
    mark_shown()
    cache = fetch_notices(cfg, force=force)
    out = render_pending(pending_notices(cfg, cache), uploads_paused(cfg, cache))
    if out:
        NOTICE_PENDING.parent.mkdir(parents=True, exist_ok=True); json.dump(out, open(NOTICE_PENDING, "w", encoding="utf-8"), indent=1)
    elif NOTICE_PENDING.exists():
        NOTICE_PENDING.unlink()
    return out

def notices_cmd(args):
    cfg = load_config() or {}
    cache = fetch_notices(cfg, force=args.fetch) or {}
    print(json.dumps({"ok": True, "fetched_at": cache.get("fetched_at"), "latest_version": cache.get("latest_version"), "installed": NAME + " " + plugin_version(),
                      "pending": pending_notices(cfg, cache), "uploads_paused": bool(uploads_paused(cfg, cache)), "seen": cache.get("seen") or []}, ensure_ascii=False, indent=1))
    return 0

def accept_notice(args):
    """`accept-notice VERSION`: the person read the current PRIVACY.md (its version must be the one installed) and accepts it."""
    cfg = load_config()
    if not cfg: print(json.dumps({"ok": False, "error": "not configured: run `stair rl setup` first"})); return 1
    if args.version != PRIVACY_NOTICE_VERSION:
        print(json.dumps({"ok": False, "error": "the installed plugin's notice is %s, not %s; update the plugin first, then read its PRIVACY.md" % (PRIVACY_NOTICE_VERSION, args.version)})); return 1
    cfg["privacy_notice"] = {"version": PRIVACY_NOTICE_VERSION, "accepted_at": now_ms()}
    json.dump(cfg, open(HOME / "config.json", "w", encoding="utf-8"), indent=1)
    refresh_notices(cfg, force=True)
    print(json.dumps({"ok": True, "privacy_notice": cfg["privacy_notice"], "uploads_paused": False})); return 0

def key_cmd(args):
    """`key rotate`: a new master key. Every wrapped session key the ledger holds for this owner is unwrapped with the old
    key, wrapped with the new one and registered again under the same id; then the new key replaces the file (the old one
    stays as master.key.old until you delete it). `key id` prints the current key's id."""
    cfg = load_config()
    if not cfg or not master_key_path(cfg): print(json.dumps({"ok": False, "error": "no content master key: run `stair rl setup` first"})); return 1
    sys.path.insert(0, cfg["sdk_src"])
    from reasoning_ledger import ContentEncryption, generate_master_key, load_master_key, master_key_id, save_master_key
    path = master_key_path(cfg); old = load_master_key(path)
    if args.key_cmd == "id": print(json.dumps({"ok": True, "master_key_id": master_key_id(old), "master_key_file": str(path)})); return 0
    c = client(cfg); fresh = ContentEncryption(master_key=generate_master_key(), agent_id=cfg.get("agent_id")); current = ContentEncryption(master_key=old)
    rewrapped = skipped = 0; after = None
    while True:
        page = c.list_content_keys(after=after, limit=500)
        for k in page.get("keys") or []:
            if k.get("master_key_id") != master_key_id(old): skipped += 1; continue
            data_key = current.unwrap(k["key_id"], k["wrapped_key"], k["master_key_id"])
            from reasoning_ledger.encryption import DataKey
            body = fresh.wrapped(DataKey(key_id=k["key_id"], key=data_key, session_id=k.get("session_id")))
            if k.get("agent_id"): body["agent_id"] = k["agent_id"]
            else: body.pop("agent_id", None)
            c.put_content_key(k["key_id"], body); rewrapped += 1
        after = page.get("next_after")
        if not after: break
    backup = path.with_suffix(".key.old"); os.replace(path, backup); save_master_key(path, fresh.master_key)
    print(json.dumps({"ok": True, "rewrapped": rewrapped, "skipped_other_keys": skipped, "master_key_id": fresh.master_key_id, "previous_key_saved_as": str(backup)}))
    return 0

def admin_request(endpoint, token, method, path, body=None):
    import urllib.request, urllib.error
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(endpoint.rstrip("/") + path, data=data, method=method,
                                 headers={"content-type": "application/json", "x-admin-token": token, "user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as res: return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("stair: the ledger answered %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))

def admin_cmd(args):
    """`admin invites new|list|revoke`: invite codes, with the ledger's administrator token (a file, never an argument)."""
    cfg = load_config() or {}
    endpoint = (args.endpoint or cfg.get("endpoint") or CHANNEL["STAIR_DEFAULT_ENDPOINT"]).rstrip("/")
    token = os.environ.get("STAIR_ADMIN_TOKEN") or os.environ.get("RL_ADMIN_TOKEN") or (open(os.path.expanduser(args.admin_token_file), encoding="utf-8").read().strip() if args.admin_token_file else "")
    if not token: raise SystemExit("stair: give --admin-token-file <file holding the administrator token> (or set STAIR_ADMIN_TOKEN)")
    if args.admin_cmd == "new":
        body = {"count": args.count, "max_uses": args.max_uses}
        if args.note: body["note"] = args.note
        if args.expires_in_days: body["expires_in_days"] = args.expires_in_days
        r = admin_request(endpoint, token, "POST", "/v1/admin/invites", body)
        for inv in r.get("invites", []): print(inv["code"])
        return 0
    if args.admin_cmd == "list":
        r = admin_request(endpoint, token, "GET", "/v1/admin/invites?limit=%d" % args.limit)
        for inv in r.get("invites", []):
            state = "revoked" if inv.get("revoked_at") else ("used up" if inv["uses"] >= inv["max_uses"] else "open")
            print("%s\t%d/%d\t%s\t%s" % (inv["code"], inv["uses"], inv["max_uses"], state, inv.get("note") or ""))
        return 0
    if args.admin_cmd == "revoke":
        r = admin_request(endpoint, token, "POST", "/v1/admin/invites/%s/revoke" % args.code.strip().upper())
        print(json.dumps({"ok": True, "code": r.get("code"), "revoked_at": r.get("revoked_at")})); return 0
    return 1

def map_cmd(args):
    cfg = load_config() or {"agent_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "stair-rl/dry")), "device": device_info()}
    st = load_state(args.transcript)
    records, new, info = process_transcript(cfg, args.transcript, {"session_id": args.conv}, st, dry=True)
    print(json.dumps({"records": len(records), "new": len(new), "info": info, "behaviors": dict(collections.Counter(r["behavior"] for r in records))}, ensure_ascii=False))
    if args.dump: json.dump(records, open(args.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0

def main():
    ap = argparse.ArgumentParser(prog="stair rl"); sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("process"); p.add_argument("--delay", type=float, default=1.5)
    s = sub.add_parser("setup"); s.add_argument("--endpoint", default=CHANNEL["STAIR_DEFAULT_ENDPOINT"], help="the ledger to write to (default: this channel's, %s)" % CHANNEL["STAIR_DEFAULT_ENDPOINT"]); s.add_argument("--agent-name", required=True)
    s.add_argument("--api-key-file", default=None, help="file holding the owner key you were given")
    s.add_argument("--register", default=None, nargs="?", const="", metavar="EMAIL", help="create an owner on the ledger (the default when this machine has no owner key yet): anonymous, or for this e-mail; the key is saved to $STAIR_HOME/owner.key")
    s.add_argument("--registration-token-file", default=None, help="for an instance without self-service: file holding its registration token (or set STAIR_REGISTRATION_TOKEN)")
    s.add_argument("--force", action="store_true", help="with --register: replace an existing owner.key")
    s.add_argument("--invite", default=None, metavar="CODE", help="with --register on a ledger that registers by invitation: your invite code (or set STAIR_INVITE_CODE); kept in config.json")
    s.add_argument("--plaintext", action="store_true", help="upload content in the clear instead of encrypting it on this machine (not for the hosted ledger)")
    s.add_argument("--accept-privacy-notice", default=None, metavar="VERSION", help="the version of PRIVACY.md the person has read and accepts (currently %s); without it setup prints the notice and stops" % PRIVACY_NOTICE_VERSION)
    s.add_argument("--sdk-src", default=os.environ.get("STAIR_SDK_SRC") or os.environ.get("RL_SDK_SRC") or str(Path.home() / "work/rl-dev/Reasoning-Ledger/python-sdk/src"))
    s.add_argument("--viewer-url", default=None, help="the viewer's public address when it differs from the endpoint (e.g. an HTTPS proxy)")
    sub.add_parser("status"); sub.add_parser("flush")
    v = sub.add_parser("viewer"); v.add_argument("--next", default=None, help="path to open after signing in"); v.add_argument("--base", default=None, help="viewer address to put in front of the ticket")
    v.add_argument("--save", action="store_true", help="remember --base as viewer_url in config.json"); v.add_argument("--json", action="store_true")
    v.add_argument("--no-key", action="store_true", help="leave the content master key out of the link (encrypted content then stays encrypted in the viewer)")
    m = sub.add_parser("map"); m.add_argument("transcript"); m.add_argument("--conv", default=None); m.add_argument("--dump", default=None)
    k = sub.add_parser("key", help="the content master key"); k.add_argument("key_cmd", choices=["id", "rotate"])
    c = sub.add_parser("claim", help="give this anonymous owner an e-mail"); c.add_argument("email")
    n = sub.add_parser("notices", help="what the plugin's makers want you to know"); n.add_argument("--fetch", action="store_true", help="fetch now instead of using the hourly cache")
    acc = sub.add_parser("accept-notice", help="accept the current privacy notice after reading PRIVACY.md"); acc.add_argument("version")
    ad = sub.add_parser("admin", help="operator commands, with the ledger's administrator token"); adsub = ad.add_subparsers(dest="admin_cmd")
    for name in ("new", "list", "revoke"):
        sp = adsub.add_parser(name); sp.set_defaults(admin_cmd=name)
        sp.add_argument("--endpoint", default=None, help="the ledger (default: the configured one, else this channel's)"); sp.add_argument("--admin-token-file", default=None, help="file holding the administrator token (or set STAIR_ADMIN_TOKEN)")
        if name == "new":
            sp.add_argument("--count", type=int, default=1); sp.add_argument("--max-uses", type=int, default=1); sp.add_argument("--note", default=None); sp.add_argument("--expires-in-days", type=int, default=None)
        if name == "list": sp.add_argument("--limit", type=int, default=200)
        if name == "revoke": sp.add_argument("code")
    ad.add_argument("what", nargs="?", default="invites", help=argparse.SUPPRESS)
    a = ap.parse_args()
    fn = {"process": process, "setup": setup, "status": status, "flush": flush, "map": map_cmd, "viewer": viewer, "key": key_cmd, "admin": admin_cmd,
          "claim": claim, "notices": notices_cmd, "accept-notice": accept_notice}.get(a.cmd)
    if fn is None: ap.print_help(); return 1
    return fn(a)

if __name__ == "__main__":
    sys.exit(main())
