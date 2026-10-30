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
import json, os, re, sys, time, uuid, hashlib, hmac, argparse, socket, getpass, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mapper import Mapper, set_fingerprint_key, strip_none  # noqa: E402

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
BATCH = 25   # records per upload; with the longer read timeout below, a slow ledger no longer times a batch out
# The privacy notice (PRIVACY.md beside this file) a person accepts at setup. Bumped whenever the notice changes in
# substance; setup then asks again.
PRIVACY_NOTICE_VERSION = "2026-10-30.1"

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

LEGACY_SDK_SRC = str(Path.home() / "work/rl-dev/Reasoning-Ledger/python-sdk/src")   # what setup stored by default before 0.11.1

def use_sdk_src(cfg):
    """Import the SDK from a development checkout only when one was asked for: STAIR_SDK_SRC, or --sdk-src at setup.
    Otherwise the plugin's own environment runs, with the SDK its channel pins, as on every user's machine."""
    p = os.environ.get("STAIR_SDK_SRC") or os.environ.get("RL_SDK_SRC")
    if not p:
        p = (cfg or {}).get("sdk_src")
        if p == LEGACY_SDK_SRC: p = None   # the old default, not a choice anyone made
    if p and os.path.isdir(p) and p not in sys.path: sys.path.insert(0, p)

def repair_event_line(line):
    """A queue line written on macOS before 0.11.1 carries "ts":<seconds>3N (its date has no %N), which is not JSON:
    keep the event, with the time in milliseconds."""
    import re
    m = re.match(r'\{"event":"([A-Za-z]+)","ts":(\d{10})[^,]*,"payload":', line)
    if not m: return None
    try: return json.loads('{"event":"%s","ts":%s000,"payload":%s' % (m.group(1), m.group(2), line[m.end():]))
    except Exception: return None

def fingerprint_key(cfg):
    """The key content fingerprints are computed with (mapper.set_fingerprint_key): HKDF-SHA256 of the content master key,
    so it never leaves this machine and changes with the master key. No master key (a plaintext ledger): plain SHA-256."""
    p = master_key_path(cfg)
    if not p: return None
    try:
        from reasoning_ledger import load_master_key
        prk = hmac.new(b"stair-fingerprint", load_master_key(p), hashlib.sha256).digest()      # HKDF extract, fixed salt
        return hmac.new(prk, b"stair fingerprint v1\x01", hashlib.sha256).digest()              # HKDF expand, one block
    except Exception as e:
        log("fingerprint-key", e); return None

def patient_transport():
    """The SDK's httpx transport with a read timeout of a minute instead of httpx's five seconds: a batch of encrypted
    records can take the ledger longer than that (50 timeouts on 10-30, each then retried one record at a time)."""
    import httpx
    from reasoning_ledger.errors import NetworkError
    from reasoning_ledger.http import HttpxTransport
    from reasoning_ledger.types import HttpResponse
    class PatientTransport(HttpxTransport):
        def request(self, req):
            try:
                res = httpx.request(method=req["method"], url=req["url"], content=req.get("body"), headers=req["headers"],
                                    timeout=httpx.Timeout(10.0, read=60.0))
            except httpx.TransportError as exc:
                raise NetworkError(f"Network error: {exc}") from exc
            return HttpResponse(body=res.text, body_bytes=res.content, headers=dict(res.headers), status=res.status_code)
    return PatientTransport()

_client = None
def client(cfg):
    global _client
    if _client is None:
        use_sdk_src(cfg)
        from reasoning_ledger import LedgerClient, LedgerClientConfig
        _client = LedgerClient(LedgerClientConfig(api_key=api_key(cfg), agent_id=cfg["agent_id"], endpoint=cfg["endpoint"], encryption=encryption_for(cfg), http_transport=patient_transport()))
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
    set_fingerprint_key(fingerprint_key(cfg))   # keyed fingerprints, from the master key
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
        except Exception:
            ev = repair_event_line(l)
            if ev is None: continue
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
    cfg = {"endpoint": args.endpoint.rstrip("/"), "api_key_file": args.api_key_file, "agent_name": args.agent_name, "device": device_info(),
           "privacy_notice": {"version": PRIVACY_NOTICE_VERSION, "accepted_at": now_ms()}}
    if getattr(args, "sdk_src", None): cfg["sdk_src"] = args.sdk_src   # a development checkout of the SDK, only when asked for
    if email: cfg["owner_email"] = email
    elif previous.get("owner_email"): cfg["owner_email"] = previous["owner_email"]
    if invite: cfg["invite_code"] = invite.strip()   # kept, so a later setup on this machine does not ask for it again
    if getattr(args, "viewer_url", None): cfg["viewer_url"] = args.viewer_url.rstrip("/")
    use_sdk_src(cfg)
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
    venv = os.environ.get("STAIR_VENV") or ""
    environment = {"python": sys.executable, "own": bool(venv) and sys.executable.startswith(venv), "sdk": os.environ.get("STAIR_SDK_SPEC_WANTED")}
    try:
        from importlib.metadata import version as dist_version
        environment["sdk_version"] = dist_version("reasoning-ledger")
    except Exception: pass
    cmd = Path.home() / ".local" / "bin" / NAME
    command = {"path": str(cmd), "kind": "absent"}
    if cmd.is_symlink(): command["kind"] = "link to %s" % os.readlink(cmd)
    elif cmd.exists(): command["kind"] = "follows the installed version" if "stair-command" in cmd.read_text(errors="replace")[:300] else "other"
    print(json.dumps({"ok": bool(cfg) and "error" not in enc, "configured": bool(cfg), "endpoint": cfg and cfg.get("endpoint"), "agent_id": cfg and cfg.get("agent_id"),
                      "transcripts": len(states), "records_uploaded": up, "queued_events": q, "spooled": sp, "home": str(HOME), "encryption": enc,
                      "privacy_notice": (cfg or {}).get("privacy_notice"), "owner": (cfg or {}).get("owner_email") or ("anonymous" if cfg else None),
                      "plugin": NAME + " " + plugin_version(), "channel": CHANNEL["STAIR_CHANNEL"], "notice_pending": NOTICE_PENDING.exists(),
                      "environment": environment, "command": command}))
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

GRANT_DAYS, GRANT_HOURS = 7, 1

def how_to_show():
    """Where a viewer link that carries a key may go: opened in this machine's browser ("open"), printed in a person's
    own terminal ("print"), or nowhere (None): run by an assistant's tool, it would put the key in the model's context."""
    import shutil
    remote = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))
    if not remote and sys.platform == "darwin" and shutil.which("open"): return "open"
    if not remote and sys.platform.startswith("linux") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and shutil.which("xdg-open"):
        return "open"
    if sys.stdout.isatty() and sys.stdin.isatty(): return "print"
    return None

def open_in_browser(url):
    import subprocess
    try:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception as e:
        log("viewer-open", e); return False

def grant_keys(cfg, days):
    """This machine's data keys of the last `days` days, newest first (at most 5000), unwrapped here with the master key."""
    import base64
    from reasoning_ledger import load_master_key, master_key_id
    from reasoning_ledger.encryption import open_sealed
    mk = load_master_key(master_key_path(cfg)); mid = master_key_id(mk); since = now_ms() - int(days * 86400 * 1000)
    found, after = [], None
    while True:
        page = owner_request(cfg, "GET", "/v1/content-keys?limit=1000&agent_id=%s%s" % (cfg["agent_id"], "&after=" + after if after else ""))
        for k in page.get("keys") or []:
            if k.get("master_key_id") == mid and (k.get("created_at") or 0) >= since:
                found.append((k["created_at"], k["key_id"], open_sealed(mk, base64.b64decode(k["wrapped_key"]), k["key_id"])))
        after = page.get("next_after")
        if not after: break
    found.sort(key=lambda f: f[0], reverse=True)
    return [(kid, dek) for _, kid, dek in found[:5000]]

def record_grant(cfg, answer, days, hours):
    """The grant, as a record in the owner's ledger: the person authorized a view of these sessions until then."""
    rec = {"schema_version": "0.5", "agent_id": cfg["agent_id"], "session_id": "stair:grants", "record_id": str(uuid.uuid4()),
           "behavior": "Attesting", "client_ts_utc": now_ms(), "executor": "human", "record_phase": "post_execution",
           "operator_id": "user", "gate_kind": "grant", "disposition": "approve", "outcome": "success", "channel": "interactive",
           "decision": {"purpose": "view", "sessions": answer.get("sessions"), "days": days, "hours": hours, "expires_at": answer.get("expires_at")},
           "written_by": {"component": "stair", "credential": "owner_api_key"}, "tags": ["grant:%s" % answer.get("grant_id")],
           "classification": {"source": "instrumented", "mapper": "stair@0.12", "confidence": 1.0}}
    try:
        _, failed = upload(cfg, [rec])
        if failed: log("grant-record", failed[0]["error"])
    except Exception as e:
        log("grant-record", e)

def make_view_grant(cfg, days, hours):
    """Grant a view: the keys of the last `days` days, wrapped again here under a fresh grant key, registered for `hours`
    hours, and the grant recorded. Returns (the ledger's answer, the grant key as a link fragment); the answer is None when
    the ledger cannot take grants (before 2.1.0), the fragment None when there is nothing to show."""
    import base64
    from reasoning_ledger import master_key_fragment, master_key_id
    from reasoning_ledger.encryption import seal
    keys = grant_keys(cfg, days)
    if not keys: return {"sessions": 0}, None
    g = os.urandom(32); gid = master_key_id(g)
    body = {"purpose": "view", "expires_in": int(hours * 3600),
            "keys": [{"key_id": kid, "master_key_id": gid, "wrap_alg": "A256GCM", "wrapped_key": base64.b64encode(seal(g, dek, kid)).decode()} for kid, dek in keys]}
    answer = owner_request(cfg, "POST", "/v1/view-grants", body, missing_ok=True)
    if answer is None: return None, None
    record_grant(cfg, answer, days, hours)
    return answer, master_key_fragment(g)

def ticket_link(cfg, base, args):
    """A one-time sign-in link without any key: the structure of the records; their content too on a ledger that keeps it
    in the clear."""
    t = mint_ticket(cfg, args.next)
    url = base + t["ticket_url"]; secs = max(0, int((t["expires_at"] - now_ms()) / 1000))
    if args.json: print(json.dumps({"ok": True, "url": url, "expires_in_s": secs, "one_time": True, "decrypts": False}))
    else: print(url); print(f"one-time link, valid for {secs} s")
    return 0

def viewer(args):
    """`viewer`: your records in the browser, decrypted there, by way of a view grant: a time-limited, revocable
    authorization for the sessions of the last --days days (7), lasting --hours hours (1). The master key never leaves this
    machine: the keys of those sessions are wrapped again here under a fresh grant key, which only the link carries (after
    #, never sent to the server), and the grant is recorded in the ledger. The link is opened in this machine's browser, or
    printed when this runs in a person's own terminal; never printed for an assistant. --no-key: the structure only."""
    cfg = load_config()
    if not cfg: print(json.dumps({"ok": False, "error": "not configured: run `stair rl setup` first"})); return 1
    if args.base and args.save:
        cfg["viewer_url"] = args.base.rstrip("/"); json.dump(cfg, open(HOME / "config.json", "w", encoding="utf-8"), indent=1)
    base = (args.base or cfg.get("viewer_url") or cfg["endpoint"]).rstrip("/")
    if not master_key_path(cfg) or getattr(args, "no_key", False): return ticket_link(cfg, base, args)
    how = how_to_show()
    if how is None:
        print(json.dumps({"ok": False, "error": "run `%s rl viewer` in a terminal of your own: its link carries a key, and an assistant is "
                                                 "not shown keys (`%s rl viewer --no-key` here shows the structure without the content)" % (NAME, NAME)}))
        return 2
    answer, fragment = make_view_grant(cfg, args.days, args.hours)
    if answer is None:
        print("stair: this ledger cannot take view grants yet (it needs 2.1.0): the structure only, without the content", file=sys.stderr)
        return ticket_link(cfg, base, args)
    if not fragment:
        print(json.dumps({"ok": True, "sessions": 0, "note": "nothing recorded on this machine in the last %s days" % args.days})); return 0
    url = base + answer["grant_url"] + "#k=" + fragment
    summary = {"ok": True, "grant_id": answer["grant_id"], "sessions": answer["sessions"], "expires_at": answer["expires_at"],
               "revoke": "%s rl revoke %s" % (NAME, answer["grant_id"])}
    if how == "open":
        if open_in_browser(url):
            print(json.dumps({**summary, "opened": "in this machine's browser"})); return 0
        if not (sys.stdout.isatty() and sys.stdin.isatty()):   # no browser, and not a person's terminal: the key goes nowhere
            print(json.dumps({**summary, "ok": False, "error": "could not open a browser; run `%s rl viewer` in a terminal of your own" % NAME})); return 1
    if args.json: print(json.dumps({**summary, "url": url}))
    else:
        until = time.strftime("%H:%M", time.localtime(answer["expires_at"] / 1000))
        print(url)
        print("opens %d sessions of the last %s days until %s; the link carries a key, so share it with nobody (`%s rl revoke %s` ends it now)"
              % (answer["sessions"], args.days, until, NAME, answer["grant_id"]))
    return 0

def grants_cmd(args):
    """`grants`: the view grants of this account, newest first, without keys."""
    cfg = load_config()
    if not cfg: print(json.dumps({"ok": False, "error": "not configured: run `stair rl setup` first"})); return 1
    r = owner_request(cfg, "GET", "/v1/view-grants", missing_ok=True)
    print(json.dumps({"ok": r is not None, "grants": (r or {}).get("grants", []), **({} if r is not None else {"error": "this ledger has no view grants yet"})}))
    return 0 if r is not None else 1

def revoke_cmd(args):
    """`revoke GRANT_ID`: end a view grant now; the ledger drops its keys and signs out the browsers it opened."""
    cfg = load_config()
    if not cfg: print(json.dumps({"ok": False, "error": "not configured: run `stair rl setup` first"})); return 1
    r = owner_request(cfg, "DELETE", "/v1/view-grants/" + args.grant_id)
    print(json.dumps({"ok": bool(r.get("revoked")), "grant_id": args.grant_id})); return 0

def owner_request(cfg, method, path, body=None, missing_ok=False):
    """A request to the ledger as this owner, outside the SDK (the few owner-account calls). missing_ok: None on a 404."""
    import urllib.request, urllib.error
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg["endpoint"].rstrip("/") + path, data=data, method=method,
                                 headers={"content-type": "application/json", "x-api-key": api_key(cfg), "user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as res: return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if missing_ok and e.code == 404: return None
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
VERSION_RE = re.compile(r"\d+(\.\d+){1,3}")                    # what a plugin version in the notices file may look like
NOTICE_VERSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}(\.\d+)?")      # and a privacy notice version: anything else is ignored

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
    if not force and cache.get("url") == url and now_ms() - (cache.get("fetched_at") or 0) < NOTICES_EVERY_MS: return cache
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as res: fetched = json.loads(res.read().decode("utf-8"))
        cache = {"fetched_at": now_ms(), "url": url, "notices": fetched.get("notices") or [], "latest_version": fetched.get("latest_version") or {},
                 "changes": fetched.get("changes") or [], "seen": cache.get("seen") or []}
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
    latest = str((cache.get("latest_version") or {}).get(NAME) or "")
    installed = plugin_version()
    if VERSION_RE.fullmatch(latest) and version_tuple(latest) > version_tuple(installed):
        # What changes between the installed version and the new one, newest first (publish.sh puts CHANGES.md there).
        changes = [c for c in cache.get("changes") or [] if isinstance(c, dict)
                   and version_tuple(installed) < version_tuple(c.get("version")) <= version_tuple(latest)]
        changes.sort(key=lambda c: version_tuple(c.get("version")), reverse=True)
        out.append({"id": "update:%s" % latest, "kind": "update", "latest": latest, "installed": installed,
                    "title": "%s %s is available (you have %s)" % (NAME, latest, installed), "changes": changes})
    accepted = ((cfg or {}).get("privacy_notice") or {}).get("version") or ""
    for n in cache.get("notices") or []:
        if not isinstance(n, dict): continue
        nid = n.get("id")
        if not isinstance(nid, str) or not nid or nid in seen: continue
        if n.get("kind") in ("changes", "update"): continue   # "what's new" for versions before 0.11.1; updates come from latest_version
        if n.get("kind") == "privacy" and not NOTICE_VERSION_RE.fullmatch(str(n.get("privacy_notice_version") or "")): continue
        if n.get("until") and str(n["until"]) < time.strftime("%Y-%m-%d"): continue
        if n.get("channel") and n["channel"] != CHANNEL["STAIR_CHANNEL"]: continue
        if n.get("kind") == "privacy" and n.get("privacy_notice_version") and str(n["privacy_notice_version"]) <= accepted: continue
        out.append(n)
    return [n for n in out if n["id"] not in seen]

def uploads_paused(cfg, cache):
    """Uploads stop when the makers published a privacy notice newer than the one this person accepted."""
    accepted = ((cfg or {}).get("privacy_notice") or {}).get("version") or ""
    for n in (cache or {}).get("notices") or []:
        v = str(n.get("privacy_notice_version") or "") if isinstance(n, dict) else ""
        if n.get("kind") == "privacy" and NOTICE_VERSION_RE.fullmatch(v) and v > accepted: return n
    return None

def changes_file(mkt):
    """Where a new version's CHANGES.md is once the marketplace is refreshed: Claude Code's copy of the marketplace (a path
    built here, not taken from the notices file); running from source, the published file."""
    if len(HERE.parents) > 3 and HERE.parents[2].name == "cache":
        return str(HERE.parents[3] / "marketplaces" / mkt / "plugins" / NAME / "CHANGES.md")
    return "https://github.com/StairAI/claude-plugins/blob/%s/plugins/%s/CHANGES.md" % ("staging" if NAME == "stair-dev" else "main", NAME)

def render_pending(pending, paused):
    """What the SessionStart hook prints. The person gets one line, which may quote the makers' words (systemMessage).
    Claude gets only sentences built here from version numbers and kinds (additionalContext), never text from the notices
    file: whoever can change that file could otherwise instruct every installed assistant without a release."""
    if not pending and not paused: return None
    mkt = "stair-ai-dev" if NAME == "stair-dev" else "stair-ai"
    update = "claude plugin marketplace update %s && claude plugin update %s@%s" % (mkt, NAME, mkt)
    lines = []; ctx = ["Stair plugin (%s) notices for this machine, shown to the person as one line. Ask before running anything." % NAME]
    for n in pending:
        kind = n.get("kind")
        if kind == "update":
            changes = n.get("changes") or []
            summary = str(changes[0].get("summary") or "").strip().rstrip(".") if changes else ""
            lines.append("Stair: %s %s is available (you have %s)%s. Say \"update stair\" to update, or ask what changed." % (NAME, n["latest"], n["installed"], ": " + summary if summary else ""))
            ctx.append("Update available: %s %s (installed: %s). If they want it, run `%s` (both, in this order: the first fetches the "
                       "marketplace), then tell them the new version applies to sessions started after the update; the `%s` command and the "
                       "plugin's Python environment follow by themselves." % (NAME, n["latest"], n["installed"], update, NAME))
            ctx.append("If they ask what it changes: run only `claude plugin marketplace update %s`, then read the entries newer than %s in %s and "
                       "tell them in their language, anything starting with \"Privacy:\" or \"You do:\" first." % (mkt, n["installed"], changes_file(mkt)))
        elif kind == "privacy":
            v = n["privacy_notice_version"]
            lines.append("Stair: the privacy notice changed (%s); recording is paused until you accept it.%s" % (v, " " + str(n["text"]) if n.get("text") else ""))
            ctx.append("The privacy notice changed to version %s and uploads are paused until the person accepts it. If the installed PRIVACY.md is "
                       "older, update the plugin first (`%s`, then a new session). Read PRIVACY.md from the plugin directory to them in their "
                       "language, ask for consent, and only with a clear yes run `%s rl accept-notice %s`." % (v, update, NAME, v))
        else:
            lines.append("Stair: " + str(n.get("title") or "") + (": " + str(n["text"]) if n.get("text") else ""))
            ctx.append("The plugin's makers left the person a message, shown to them; you are not given its words.")
    if paused and not any(n.get("kind") == "privacy" for n in pending):
        lines.append("Stair: recording is paused until the new privacy notice (%s) is accepted." % paused["privacy_notice_version"])
        ctx.append("Uploads are paused until the person accepts privacy notice %s: update the plugin if its PRIVACY.md is older (`%s`), read "
                   "PRIVACY.md to them, and only with a clear yes run `%s rl accept-notice %s`." % (paused["privacy_notice_version"], update, NAME, paused["privacy_notice_version"]))
    return {"ids": [n["id"] for n in pending], "for_version": plugin_version(), "systemMessage": " ".join(lines),
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
    use_sdk_src(cfg)
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
    s.add_argument("--sdk-src", default=os.environ.get("STAIR_SDK_SRC") or os.environ.get("RL_SDK_SRC"), help="a development checkout of the SDK (its src directory) to use instead of the plugin's own environment")
    s.add_argument("--viewer-url", default=None, help="the viewer's public address when it differs from the endpoint (e.g. an HTTPS proxy)")
    sub.add_parser("status"); sub.add_parser("flush")
    v = sub.add_parser("viewer"); v.add_argument("--next", default=None, help="path to open after signing in"); v.add_argument("--base", default=None, help="viewer address to put in front of the ticket")
    v.add_argument("--days", type=float, default=GRANT_DAYS, help="grant a view of the sessions of the last DAYS days (default %(default)s)"); v.add_argument("--hours", type=float, default=GRANT_HOURS, help="for HOURS hours, at most 24 (default %(default)s)")
    sub.add_parser("grants", help="your view grants, newest first"); rv = sub.add_parser("revoke", help="end a view grant now"); rv.add_argument("grant_id")
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
          "claim": claim, "notices": notices_cmd, "accept-notice": accept_notice, "grants": grants_cmd, "revoke": revoke_cmd}.get(a.cmd)
    if fn is None: ap.print_help(); return 1
    return fn(a)

if __name__ == "__main__":
    sys.exit(main())
