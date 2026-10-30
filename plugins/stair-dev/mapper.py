# -*- coding: utf-8 -*-
"""Transcript -> schema 0.5 records (the batch design).

Reads a Claude Code transcript (JSONL) and returns one record per behavior, by rule:

  a message that opens a turn       -> Observing; who sent it comes from the line's origin, never from the model:
    the person                       -> human_trigger
    another session (the brief of a session it started, a cross-session message, a sub-agent's report)
                                     -> agent_trigger, sources naming the sender; a "link:<digest>" tag pairs it with the
                                        sender's Delegating (same digest of the brief or message on both sides)
    a background task that finished  -> outcome_trigger, sources pointing at the call that started it
    a notice from the app            -> signal_trigger
    upstream = the Acting of the turn it continues
  "[Request interrupted by user]"    -> Attesting(gate_kind=interrupt, cancel) in the turn it stops; not a turn
  thinking block                     -> Thinking (model_invocation from the message); the text stays on the machine, the record carries its hash and size (thinking_text="hash", the default)
  mid-turn assistant text            -> Thinking / Reflecting when a sentence states a decision or a verdict (rule, confidence 0.5),
                                        else Other(assistant.narration, proposed_behavior=Reporting)
  final assistant text               -> Acting (answer.final); a text that ends by asking the user -> Escalating(question)
  tool_use + tool_result             -> ToolCalling (call_id, duration, outcome, effect; file writes carry a pointer, not content)
    Agent / Task / SendMessage       -> Delegating (a sub-agent's id from the call's result names its sessions)
    start_session / hand_off_to_session / send_message (sessions of the Claude app) -> Delegating(spawn | handoff | message),
                                        the started session as child_session_id "claude-code-app://local_…"
    AskUserQuestion                  -> Escalating(question) + Attesting from the answer
    Write/Edit to memory, CLAUDE.md, skills, settings -> Memorizing (target = pointer + change hash)
    TodoWrite / plan tools           -> Planning (goal, steps)
    a reply that lays out a numbered plan (the word "plan" + 2+ numbered items) -> Planning (confidence 0.6)
    verify-like Bash                 -> an extra Reflecting(kind=evaluation, concurrent)
  permission events (from hooks)     -> Escalating(permission) + Attesting(approve | reject | no_response)
  compaction line, or a continuation summary written as a message -> Other(context.compaction)
  rewind (a prompt whose parent is an earlier turn) -> tag rewound_to:t<k> + Attesting(gate_kind=rewind, reject)
  fork (first prompt's parent is not in this file) -> tag forked_from + sources pointing at that record id
  fork made by the app (the file starts with the parent's lines, under the parent's sessionId) -> that copied history is
    walked but not emitted (it happened in the parent session); the first own turn is tagged fork_of:<parent session>
    and points at the parent's turn through sources, never upstream (the parent's records may live under another agent)

Record ids derive from message / tool_use ids, so a copied history (fork, continuation) or a re-run maps to the same ids
and the server's (agent_id, record_id) dedup keeps one copy. Links across sessions travel in sources and tags, never in
upstream_record_id: the server checks that an upstream record exists under the same agent, and sessions upload in any
order. Nothing here touches the network.
"""
from __future__ import annotations
import hashlib, hmac, json, os, re, uuid, datetime
from pathlib import Path

NS = uuid.NAMESPACE_URL
READ = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "NotebookRead", "ToolSearch", "ListAgents", "ReadNotifications", "Monitor"}
WRITE = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PLAN = {"TodoWrite", "TaskCreate", "TaskUpdate", "ExitPlanMode", "mcp__ccd_turn__update_plan"}
VERIFY = re.compile(r"\b(pytest|python3? -m pytest|npm (run )?test|pnpm (run )?test|vitest|jest|cargo test|go test|make test|tsc\b|eslint|ruff|mypy|playwright|screenshot|typecheck|test-local)", re.I)
DECISION = re.compile(r"\b(I'?ll (leave|skip|not|keep|use|go with)|I will (leave|skip|not|keep|use)|decid\w+|instead of|rather than|out of (my )?scope|not (part of|in) (my|the|this) task|leave it|unrelated to)\b", re.I)
VERDICT = re.compile(r"\b(\d+ passed|\d+ failed|all tests pass|tests? (pass|passes|passed|fail|fails|failed)|passes|passed|failed|is green|is red|confirmed|verified)\b", re.I)
NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.+?)\s*$", re.M)
PLAN_WORD = re.compile(r"\bplan\b", re.I)
QUESTION_END = re.compile(r"\?\s*$|\b(which (one|option) (do you|would you)|should I|do you want me to|would you like me to)\b[^.]*\?|\b(tell me which|let me know which|which (one|option) (would|do) you)\b", re.I)   # a closing "let me know if…" is not a question
ERR_TYPES = [("permission.denied", re.compile(r"doesn't want to proceed|user declined|denied|requires? approval|needs approval", re.I)),
             ("file.not_found", re.compile(r"ENOENT|No such file|does not exist|not found", re.I)),
             ("tool.timeout", re.compile(r"timed? ?out", re.I)), ("tool.invalid_input", re.compile(r"InputValidationError|invalid|must be", re.I)),
             ("shell.error", re.compile(r"exit code|command failed|Error:", re.I))]
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
CROSS_SESSION = re.compile(r'^<cross-session-message from="([^"]+)"[^>]*>\n?(.*?)(?:</cross-session-message>)?\s*$', re.S)
APP_SESSION = re.compile(r"\blocal_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
TASK_NOTE = re.compile(r"<task-notification>.*?<tool-use-id>([A-Za-z0-9_]+)</tool-use-id>", re.S)
AGENT_ID = re.compile(r"\bagentId:?\s*([0-9a-f]{8,})")
SESSION_REPORT = re.compile(r"finished a turn|\breported\b|you started|The user's fork|forked this conversation", re.I)
INTERRUPTED = re.compile(r"^\[Request interrupted by user[^\]]*\]$")
CONTINUED = "This session is being continued from a previous conversation"
BRIEF_HEAD, BRIEF_TASK = "Background (from the session that started this one):", "\n\nTask:\n"
SESSION_TOOLS = ("__start_session", "__hand_off_to_session")
TRIGGER_WORDS = {"human_trigger": "user prompt", "agent_trigger": "message from another session or agent",
                 "outcome_trigger": "a background task finished", "signal_trigger": "notice from the app"}

def norm_text(s):
    """Text as both ends of a hand-over see it: the app writes @ as a full-width ＠ when it passes text between sessions."""
    return (s or "").replace("\uff20", "@").replace("\r\n", "\n").strip()

_FP_KEY = None

def set_fingerprint_key(key):
    """Content fingerprints (the prompt that opened a turn, a brief or message handed to another session, a file write, a
    thinking block, a verdict sentence, what a question was given) are HMAC-SHA256 with this key once it is set. The plugin
    derives it from the content master key, so the same text still matches across this owner's sessions while the ledger
    cannot test guesses against it, not even for a one-word prompt. Unset (tests, a plaintext ledger) they are SHA-256."""
    global _FP_KEY
    _FP_KEY = key

def fingerprint(raw):
    return hmac.new(_FP_KEY, raw, hashlib.sha256).hexdigest() if _FP_KEY else hashlib.sha256(raw).hexdigest()

def link_key(s):
    """The tag that pairs a Delegating with the turn it started in the other session: a fingerprint of the brief or message."""
    return "link:" + fingerprint(norm_text(s).encode("utf-8"))[:16]

def rid(*parts): return str(uuid.uuid5(NS, "stair-ai.com/stair-rl/" + "/".join(str(p) for p in parts)))
def sha(obj):
    raw = obj.encode("utf-8") if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return fingerprint(raw)
def ts_ms(s):
    try: return int(datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception: return None
def error_type(text):
    for k, rx in ERR_TYPES:
        if rx.search(text or ""): return k
    return "tool.error"
def mem_scope(path):
    p = path or ""
    if "/memory/" in p: return "project"
    if p.endswith("CLAUDE.md"): return "user" if "/.claude/" in p else "project"
    if "/skills/" in p or p.endswith("SKILL.md"): return "user"
    if "/.claude/" in p and ("settings" in p or "hooks" in p or "keybindings" in p): return "user"
    return None
def claim_shape(sentence):
    """What the ledger keeps of a verdict sentence found in the agent's own text: its length and digest. The sentence itself
    is inside the record's output, which is content and travels encrypted."""
    return {"sentence_chars": len(sentence), "sentence_sha256": sha(sentence)}

def plan_steps(text):
    """A reply that lays out its plan as a numbered list: the steps, or None. Needs the word "plan" and two or more items."""
    if not text or not PLAN_WORD.search(text): return None
    items = [m.group(2).strip()[:200] for m in NUMBERED.finditer(text)]
    return items if len(items) >= 2 else None

def first_sentence(text, rx):
    for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text or ""):
        if rx.search(s): return s.strip()[:240]
    return None

def file_pointer(device, path, written):
    """What a write touched, without its content: a globally unique pointer plus the hash of what was written."""
    p = str(path or "")
    return {"kind": "file", "device_id": device.get("device_id"), "host": device.get("host"), "user": device.get("user"),
            "path": os.path.abspath(p) if p else None, "change_sha256": sha(written) if written is not None else None,
            "change_bytes": len(written.encode("utf-8")) if isinstance(written, str) else None}

def thinking_fingerprint(text):
    """What the ledger gets instead of a thinking block's text: its size and SHA-256, as a small JSON document that the SDK
    uploads as content like any other payload. The record stays a complete schema 0.5 record (Thinking requires an
    output_payload, and every content reference in a record must point at content the ledger holds); the text itself never
    leaves the machine. A block whose text is absent from the transcript is marked as such."""
    data = (text or "").encode("utf-8")
    return json.dumps({"thinking": "withheld" if data else "absent", "sha256": fingerprint(data), "bytes": len(data)}, sort_keys=True)


class Mapper:
    def __init__(self, agent_id, device, mapper_name="stair@0.3", component="stair", credential="owner_api_key", thinking_text="hash"):
        self.thinking_text = thinking_text  # "hash": the record carries only a fingerprint (sha256 + size) of each thinking block; "full": the text is uploaded as content
        self.agent_id = agent_id; self.device = device or {}; self.mapper = mapper_name
        self.wb = {"component": component, "credential": credential}

    # ---- record helpers
    def base(self, sid, behavior, ts, executor, phase, conf=1.0, source="rule", tags=None, **fields):
        r = {"schema_version": "0.5", "agent_id": self.agent_id, "session_id": sid, "behavior": behavior, "client_ts_utc": ts or 0,
             "executor": executor, "record_phase": phase, "written_by": dict(self.wb),
             "classification": {"source": source, "mapper": self.mapper, "confidence": conf}}
        if tags: r["tags"] = tags[:32]
        r.update({k: v for k, v in fields.items() if v is not None}); return r

    def mi_of(self, m, d):
        usage = m.get("usage") or {}
        mi = {"provider": "anthropic", "model_name": m.get("model") or "unknown", "invocation_kind": "live",
              "tokens_in": (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0),
              "tokens_out": usage.get("output_tokens"), "cache_read_tokens": usage.get("cache_read_input_tokens"),
              "cache_creation_tokens": usage.get("cache_creation_input_tokens"), "finish_reason": m.get("stop_reason"), "request_id": d.get("requestId")}
        return {k: v for k, v in mi.items() if v is not None}

    # ---- the main pass
    def map_transcript(self, path, conv_id, permission_events=None, subagent_events=None, child_prefix=None, parent_ref=None):
        """Returns (records, info). conv_id prefixes every session id; child_prefix marks a sub-agent transcript, whose
        first prompt came from the Delegating record parent_ref (when the caller knows it)."""
        lines = []
        for line in open(path, encoding="utf-8"):
            try: lines.append(json.loads(line))
            except Exception: continue
        perms = list(permission_events or [])
        out = []; turn = 0; sid = None; tags_turn = []
        last_text = None; last_text_ts = None; last_text_uuid = None; last_text_mi = None
        prev = []                      # record ids in this turn, for upstream links
        tool_use = {}                  # tool_use id -> pending record info
        turn_of_uuid = {}              # message uuid -> turn index
        acting_of_turn = {}            # turn index -> Acting record id
        turn_first_ts = {}
        in_file = {d.get("uuid") for d in lines if d.get("uuid")}
        info = {"turns": 0, "rewinds": 0, "forks": 0, "compactions": 0}
        # A fork made by the app starts with the parent's lines, still under the parent's sessionId. The file's own session
        # is the one its last lines carry; the copied history before it is walked (for turn numbers and links) but not
        # emitted: it happened in the parent session and was recorded there, under the same record ids.
        own_sid = None if child_prefix else next((d.get("sessionId") for d in reversed(lines) if d.get("sessionId")), None)
        first_sid = next((d.get("sessionId") for d in lines if d.get("sessionId")), None)
        fork_of = first_sid if own_sid and first_sid and first_sid != own_sid else None
        own_from = next((i for i, d in enumerate(lines) if d.get("sessionId") == own_sid), 0) if fork_of else 0
        emitted_from = 0               # where this session's own records start in `out`
        own_turns = 0                  # turns opened in this session's own lines
        agent_spawn = {}               # sub-agent id -> the Delegating that started it (from the Agent call's result)
        session_spawn = {}             # app session id -> the Delegating that started it (from start_session's result)
        def classify(d, text, first):
            """Who sent the message that opens a turn, from the line itself: (trigger_type, trigger_source, executor, sources, tags)."""
            o = d.get("origin") if isinstance(d.get("origin"), dict) else {}
            kind = str(o.get("kind") or d.get("turnOrigin") or "")
            body = REMINDER.sub("", text).strip()
            if child_prefix and first:   # a sub-agent's first prompt is the brief its parent wrote
                return ("agent_trigger", "claude-code://subagent_prompt", "ai", [{"kind": "record", "ref": parent_ref}] if parent_ref else [], [])
            if kind in ("task-notification", "task_notification") or body.startswith("<task-notification>"):
                m = TASK_NOTE.search(body)
                return ("outcome_trigger", "claude-code://task_notification", "det", [{"kind": "record", "ref": rid(self.agent_id, m.group(1), "tool")}] if m else [], [])
            if kind == "peer":
                frm = str(o.get("from") or o.get("senderTaskId") or "")[:64]
                src = ([{"kind": "agent", "ref": frm}] if frm else []) + ([{"kind": "record", "ref": agent_spawn[frm]}] if frm in agent_spawn else [])
                return ("agent_trigger", "claude-code://agent_message", "ai", src, [])
            m = CROSS_SESSION.match(body)
            if m:
                k = link_key(m.group(2))
                return ("agent_trigger", "claude-code://session_message", "ai", [{"kind": "session", "ref": m.group(1)[:64]}, {"kind": "delegation", "ref": k}], [k])
            if kind == "sdk" and first and body and not body.startswith("<"):   # the brief of a session another session started
                task = body.split(BRIEF_TASK, 1)[1] if body.startswith(BRIEF_HEAD) and BRIEF_TASK in body else body
                k = link_key(task)
                return ("agent_trigger", "claude-code://session_start", "ai", [{"kind": "delegation", "ref": k}], [k])
            if kind == "sdk" or not body:   # written by the app, not typed by the person
                ids = list(dict.fromkeys(APP_SESSION.findall(text)))
                if ids and SESSION_REPORT.search(text):
                    src = [{"kind": "session", "ref": i} for i in ids[:4]] + [{"kind": "record", "ref": session_spawn[i]} for i in ids[:4] if i in session_spawn]
                    return ("agent_trigger", "claude-code://session_report", "ai", src, [])
                return ("signal_trigger", "claude-code://app_notice", "det", [], [])
            return ("human_trigger", "claude-code://user_prompt", "human", [{"kind": "human", "ref": "user", "sha256": sha(text)}], [])
        def narration_or_claim(text, ts, u, i, mi):
            steps = plan_steps(text)
            if steps:   # the reply laid out a numbered plan before acting on it
                # Structure only in the Planning record (the ledger can read it); the plan's text travels encrypted,
                # as the output of a companion Thinking record that the plan points at.
                said = self.base(sid, "Thinking", ts, "ai", "post_execution", conf=0.6, tags=tags_turn, output_payload=text, outcome="success",
                                 model_invocation=mi, record_id=rid(self.agent_id, u, "plan-said", i))
                plan = self.base(sid, "Planning", ts, "ai", "post_execution", conf=0.6, tags=tags_turn, goal="plan stated in the reply, %d chars" % len(text),
                                 steps=[{"index": j, "description": "step %d, %d chars" % (j + 1, len(d))} for j, d in enumerate(steps)], outcome="success",
                                 record_id=rid(self.agent_id, u, "plan-text", i))
                plan["upstream_record_id"] = [said["record_id"]]; plan["_before"] = [said]
                return plan
            s = first_sentence(text, VERDICT)
            if s:
                return self.base(sid, "Reflecting", ts, "ai", "concurrent", conf=0.5, tags=tags_turn, kind="evaluation",
                                 inputs=[], output_payload=text, verdict={"conclusion": claim_shape(s), "decided_by": "model"}, outcome="success", model_invocation=mi,
                                 record_id=rid(self.agent_id, u, "claim", i))
            s = first_sentence(text, DECISION)
            if s:
                return self.base(sid, "Thinking", ts, "ai", "post_execution", conf=0.5, tags=tags_turn, output_payload=text,
                                 verdict={"conclusion": claim_shape(s), "decided_by": "model"}, outcome="success", model_invocation=mi, record_id=rid(self.agent_id, u, "claim", i))
            return self.base(sid, "Other", ts, "ai", "post_execution", tags=tags_turn, label="assistant.narration", data={"chars": len(text)},
                             proposed_behavior="Reporting", record_id=rid(self.agent_id, u, "narr", i))
        def flush_text():
            nonlocal last_text
            if last_text is None or not sid: return
            text, ts, u, mi = last_text, last_text_ts, last_text_uuid, last_text_mi
            asks = bool(QUESTION_END.search(text.strip()[-300:]))
            delivered = len(text) > 300 or bool(re.search(r"\b(done|fixed|added|implemented|completed|updated|wrote|created|recorded)\b", text, re.I))
            if delivered or not asks:   # the turn handed a result over
                r = self.base(sid, "Acting", ts, "ai", "post_execution", tags=tags_turn, action_type="answer.final", target_system="user",
                              action_summary="final answer, %d chars" % len(text), parameters={"chars": len(text)}, output_payload=text, execution_status="confirmed",
                              outcome="success", model_invocation=mi, duration_ms=(ts - turn_first_ts[turn]) if ts and turn_first_ts.get(turn) else None,
                              record_id=rid(self.agent_id, u, "final"))
                if prev: r["upstream_record_id"] = prev[-1:]
                out.append(r); acting_of_turn[turn] = r["record_id"]; prev.append(r["record_id"])
            if asks:   # the turn ended by asking the person something: an open Escalating, answered (if ever) by the next prompt
                q = self.base(sid, "Escalating", ts, "ai", "pre_execution", tags=tags_turn, kind="question", asked=text[-600:], outcome="escalated",
                              model_invocation=mi, record_id=rid(self.agent_id, u, "final-q"))
                if prev: q["upstream_record_id"] = prev[-1:]
                out.append(q)
                if turn not in acting_of_turn: acting_of_turn[turn] = q["record_id"]
            last_text = None
        for li, d in enumerate(lines):
            t = d.get("type"); m = d.get("message") or {}; ts = ts_ms(d.get("timestamp")); u = d.get("uuid")
            in_prefix = bool(fork_of) and li < own_from
            if fork_of and li == own_from:
                flush_text(); emitted_from = len(out)   # everything before this was the parent's
            if u: turn_of_uuid[u] = turn
            if t == "user" and d.get("isCompactSummary"):
                if sid:
                    r = self.base(sid, "Other", ts, "det", "post_execution", tags=tags_turn, label="context.compaction", data={"chars": len(str(m.get("content")))}, record_id=rid(self.agent_id, u, "compact"))
                    if prev: r["upstream_record_id"] = prev[-1:]
                    out.append(r); prev.append(r["record_id"]); info["compactions"] += 1
                continue
            if t == "user":
                c = m.get("content"); text = None; results = []
                if isinstance(c, str): text = c
                elif isinstance(c, list):
                    for x in c:
                        if isinstance(x, dict) and x.get("type") == "text": text = (text or "") + x.get("text", "")
                        if isinstance(x, dict) and x.get("type") == "tool_result": results.append(x)
                for x in results:
                    tu = tool_use.get(x.get("tool_use_id"))
                    if not tu or tu.get("kind") == "skip": continue
                    rec, kind = tu["rec"], tu["kind"]; content = x.get("content"); ctext = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)[:4000]
                    err = bool(x.get("is_error")); rec["duration_ms"] = max(0, ts - tu["ts"]) if ts and tu.get("ts") else None
                    denied = err and bool(re.search(r"doesn't want to proceed|user declined|denied|requires? approval|needs approval", ctext, re.I))
                    perm = tu.get("perm")
                    if perm:
                        disp = "reject" if denied else "approve"
                        att = self.base(sid, "Attesting", ts, "human", "concurrent", conf=0.9, tags=tags_turn, operator_id="user", gate_kind="permission", disposition=disp,
                                        outcome="success", channel="interactive", seen_digest=sha(tu["inp"]), seen_completeness="complete",
                                        duration_ms=max(0, ts - perm["ts"]) if ts and perm.get("ts") else None, record_id=rid(self.agent_id, x.get("tool_use_id"), "perm-att"))
                        att["upstream_record_id"] = [perm["record_id"]]
                        if denied: att["reason"] = "user declined the permission prompt"
                        out.append(att); prev.append(att["record_id"])
                    if kind == "tool":
                        rec["output_payload"] = content if content is not None else ""
                        rec["outcome"] = "denied" if denied else ("failure" if err else "success")
                        if err: rec["error_type"] = "permission.denied" if denied else error_type(ctext)
                        if tu.get("verify"):
                            rf = self.base(sid, "Reflecting", ts, "ai", "concurrent", conf=0.6, tags=tags_turn, kind="evaluation",
                                           inputs=[{"input_record_id": rec["record_id"], "input_payload": content if content is not None else ""}],
                                           output_payload="verification read: %s" % ("failed" if err else "ok"),
                                           verdict={"conclusion": {"ok": not err}, "decided_by": "rule", "rule_ref": ["stair.verify-command"]},
                                           outcome="failure" if err else "success", record_id=rid(self.agent_id, x.get("tool_use_id"), "refl"))
                            rf["upstream_record_id"] = [rec["record_id"]]; out.append(rf); prev.append(rf["record_id"])
                    elif kind == "delegate":
                        rec["result"] = content if content is not None else ""; rec["outcome"] = "failure" if err else "success"
                        if err: rec["error_type"] = error_type(ctext)
                        tname = tu.get("name") or ""
                        # the result's own text (a list of blocks is joined, not serialized: escaped newlines would hide the ids)
                        ptext = content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content if isinstance(b, dict)) if isinstance(content, list) else ""
                        if tname.endswith(SESSION_TOOLS) and not err:   # the app answers with the started session's id
                            ids = APP_SESSION.findall(ptext)
                            if ids and re.search(r"\b(Started|Handed|started|handed)\b", ptext):
                                rec["child_session_id"] = "claude-code-app://" + ids[0]; session_spawn[ids[0]] = rec["record_id"]
                            elif re.search(r"Do it here", ptext): rec["outcome"] = "cancelled"
                            elif re.search(r"\b(No |not |cannot|can't|failed|refused|error)", ptext): rec["outcome"] = "failure"; rec["error_type"] = error_type(ptext)
                            else: rec["outcome"] = "escalated"   # proposed to the person, not started
                        elif tname in ("Agent", "Task") and not err:
                            a = AGENT_ID.search(ptext)
                            if a:
                                agent_spawn[a.group(1)[:64]] = rec["record_id"]; rec["child_session_id"] = "%s:sub:%s" % (conv_id, a.group(1)[:8])
                    elif kind in ("memorize", "plan"):
                        rec["outcome"] = "failure" if err else "success"
                        if err: rec["error_type"] = error_type(ctext)
                    elif kind == "ask":
                        rec["outcome"] = "cancelled" if err else "success"
                        if not err:
                            ans = re.findall(r'"([^"]*)"="([^"]*)"', ctext); chosen = [a for _, a in ans]; opts = set(tu.get("options") or [])
                            disp = "approve" if chosen and all(re.sub(r"\s*\(Recommended\)$", "", a.strip()) in opts or a.strip() in opts for a in chosen) else "edit"
                            att = self.base(sid, "Attesting", ts, "human", "concurrent", conf=0.8, tags=tags_turn, operator_id="user", gate_kind="question", disposition=disp,
                                            decision={"answers": len(chosen)}, outcome="success", channel="interactive", seen_digest=sha(tu["inp"]), seen_completeness="complete",
                                            duration_ms=rec["duration_ms"], record_id=rid(self.agent_id, x.get("tool_use_id"), "att"))
                            att["upstream_record_id"] = [rec["record_id"]]; out.append(att)
                            prev.append(att["record_id"])
                    prev.append(rec["record_id"])
                body = REMINDER.sub("", text or "").strip()
                if text and not results and not d.get("isMeta") and INTERRUPTED.match(body):   # the person stopped the turn
                    if sid:
                        flush_text()
                        att = self.base(sid, "Attesting", ts, "human", "concurrent", conf=0.9, tags=tags_turn, operator_id="user", gate_kind="interrupt", disposition="cancel",
                                        reason="the person stopped the turn", outcome="cancelled", channel="interactive", record_id=rid(self.agent_id, u, "interrupt"))
                        if prev: att["upstream_record_id"] = prev[-1:]
                        out.append(att); prev.append(att["record_id"])
                    continue
                if text and not results and body.startswith(CONTINUED):   # a continuation summary written as a message
                    if sid:
                        r = self.base(sid, "Other", ts, "det", "post_execution", tags=tags_turn, label="context.compaction", data={"chars": len(text)}, record_id=rid(self.agent_id, u, "compact"))
                        if prev: r["upstream_record_id"] = prev[-1:]
                        out.append(r); prev.append(r["record_id"]); info["compactions"] += 1
                    continue
                if text is not None and text.strip() and not results and not d.get("isMeta"):
                    flush_text(); turn += 1
                    first_own = not in_prefix and own_turns == 0
                    if in_prefix: info["copied_turns"] = info.get("copied_turns", 0) + 1
                    else: info["turns"] += 1; own_turns += 1
                    sid = "%s:t%03d" % (conv_id, turn) if not child_prefix else "%s:t%03d" % (child_prefix, turn)
                    prev = []; tags_turn = ["conv:" + conv_id]; turn_first_ts[turn] = ts
                    parent = d.get("parentUuid"); upstream = None
                    trig, trig_src, trig_ex, sources, link_tags = classify(d, text, first_own)
                    if fork_of and first_own:   # the first turn after the parent's copied history: a fork of that turn
                        tags_turn.append("fork_of:" + fork_of); info["forks"] += 1
                        if parent and parent in turn_of_uuid and acting_of_turn.get(turn_of_uuid[parent]):
                            sources.append({"kind": "record", "ref": acting_of_turn[turn_of_uuid[parent]]})
                    elif parent and parent in turn_of_uuid and turn_of_uuid[parent] and turn_of_uuid[parent] != turn - 1 and acting_of_turn.get(turn_of_uuid[parent]):
                        k = turn_of_uuid[parent]; tags_turn.append("rewound_to:t%03d" % k); info["rewinds"] += 1
                        upstream = [acting_of_turn[k]]
                        att = self.base(sid, "Attesting", ts, "human", "concurrent", conf=0.8, tags=tags_turn, operator_id="user", gate_kind="rewind", disposition="reject",
                                        reason="the person rewound the conversation to turn %d" % k, decision={"rewound_to": k, "abandoned_turns": list(range(k + 1, turn))},
                                        outcome="success", channel="interactive", record_id=rid(self.agent_id, u, "rewind"))
                        att["upstream_record_id"] = [acting_of_turn[k]]; out.append(att); prev.append(att["record_id"])
                    elif parent and parent in turn_of_uuid and acting_of_turn.get(turn_of_uuid[parent]):
                        upstream = [acting_of_turn[turn_of_uuid[parent]]]
                    elif parent and parent not in in_file and turn == 1:
                        tags_turn.append("forked_from:" + rid(self.agent_id, parent, "final")[:8]); info["forks"] += 1
                        sources.append({"kind": "record", "ref": rid(self.agent_id, parent, "final")})
                    r = self.base(sid, "Observing", ts, trig_ex, "pre_execution", tags=tags_turn + link_tags, trigger_source=trig_src, trigger_type=trig,
                                  trigger_description="%s, %d chars" % (TRIGGER_WORDS[trig], len(text)), trigger_payload_summary="%d chars" % len(text), trigger_payload=text,
                                  sources=sources or None, record_id=rid(self.agent_id, u, "obs"))
                    if upstream: r["upstream_record_id"] = upstream
                    out.append(r); prev.append(r["record_id"])
                continue
            if t != "assistant" or not sid: continue
            mi = self.mi_of(m, d)
            for i, x in enumerate(m.get("content") or []):
                if not isinstance(x, dict): continue
                k = x.get("type")
                if k == "thinking":
                    t = x.get("thinking") or ""
                    full = self.thinking_text == "full"   # "full": the text goes up as content; otherwise only its fingerprint does
                    r = self.base(sid, "Thinking", ts, "ai", "post_execution", tags=tags_turn, output_payload=t if full else thinking_fingerprint(t), outcome="success",
                                  model_invocation=dict(mi, internal_reasoning=t) if full else dict(mi), record_id=rid(self.agent_id, u, "think", i))
                    if prev: r["upstream_record_id"] = prev[-1:]
                    out.append(r); prev.append(r["record_id"])
                elif k == "text" and (x.get("text") or "").strip():
                    if last_text is not None:
                        r = narration_or_claim(last_text, last_text_ts, last_text_uuid, 0, last_text_mi)
                        for c in r.pop("_before", []):
                            if prev: c["upstream_record_id"] = prev[-1:]
                            out.append(c); prev.append(c["record_id"])
                        if prev and "upstream_record_id" not in r: r["upstream_record_id"] = prev[-1:]
                        out.append(r); prev.append(r["record_id"])
                    last_text, last_text_ts, last_text_uuid, last_text_mi = x.get("text"), ts, "%s-%d" % (u, i), mi
                elif k == "tool_use":
                    name = x.get("name") or "unknown"; inp = x.get("input") or {}; tid = x.get("id")
                    if name == "Bash" and ("/bin/stair" in str(inp.get("command") or "") or "/bin/rl " in str(inp.get("command") or "")):   # the plugin's own commands are not behavior of the session
                        tool_use[tid] = {"kind": "skip"}; continue
                    if last_text is not None:
                        r = narration_or_claim(last_text, last_text_ts, last_text_uuid, 0, last_text_mi)
                        for c in r.pop("_before", []):
                            if prev: c["upstream_record_id"] = prev[-1:]
                            out.append(c); prev.append(c["record_id"])
                        if prev and "upstream_record_id" not in r: r["upstream_record_id"] = prev[-1:]
                        out.append(r); prev.append(r["record_id"]); last_text = None
                    up = prev[-1:]
                    perm = None
                    for pe in perms:   # a permission prompt for this tool (by id, else by name within 60 s before)
                        if pe.get("used"): continue
                        if (pe.get("tool_use_id") and pe["tool_use_id"] == tid) or (not pe.get("tool_use_id") and pe.get("tool_name") == name and ts and abs(ts - (pe.get("ts") or 0)) < 60000):
                            pe["used"] = True
                            esc = self.base(sid, "Escalating", pe.get("ts") or ts, "ai", "pre_execution", tags=tags_turn, kind="permission", asked={"tool": name, "input": inp},
                                            outcome="success" if not pe.get("denied") else "success", record_id=rid(self.agent_id, tid, "perm"))
                            if up: esc["upstream_record_id"] = up
                            out.append(esc); prev.append(esc["record_id"]); perm = {"record_id": esc["record_id"], "ts": pe.get("ts")}; up = [esc["record_id"]]
                            break
                    common = dict(tags=tags_turn)
                    if name in ("Agent", "Task"):
                        rec = self.base(sid, "Delegating", ts, "ai", "post_execution", kind="spawn", goal=inp.get("prompt") or inp, delegate_agent_id=str(inp.get("subagent_type") or "general-purpose"),
                                        awaited=True, model_invocation=mi, record_id=rid(self.agent_id, tid, "tool"), **common); kind = "delegate"
                    elif name.endswith(SESSION_TOOLS):   # a session of the Claude app, started or handed over
                        handoff = name.endswith("__hand_off_to_session")
                        task = inp.get("remaining_plan") if handoff else inp.get("prompt")
                        goal = ({"background": inp["background"], "task": task} if inp.get("background") else task) if task else inp
                        rec = self.base(sid, "Delegating", ts, "ai", "post_execution", kind="handoff" if handoff else "spawn", goal=goal, delegate_agent_id="claude-code-session",
                                        awaited=False, model_invocation=mi, record_id=rid(self.agent_id, tid, "tool"),
                                        tags=tags_turn + ([link_key(task)] if isinstance(task, str) and task.strip() else [])); kind = "delegate"
                    elif name == "SendMessage" or name.endswith("__send_message"):
                        msg = inp.get("message") or inp.get("content")
                        rec = self.base(sid, "Delegating", ts, "ai", "post_execution", kind="message", goal=msg or inp,
                                        delegate_agent_id=str(inp.get("to") or inp.get("session_id") or "session")[:40], awaited=False, record_id=rid(self.agent_id, tid, "tool"),
                                        tags=tags_turn + ([link_key(msg)] if isinstance(msg, str) and msg.strip() else [])); kind = "delegate"
                    elif name == "AskUserQuestion":
                        qs = inp.get("questions") or []; opts = [o.get("label") for q in qs for o in (q.get("options") or []) if isinstance(o, dict) and o.get("label")]
                        rec = self.base(sid, "Escalating", ts, "ai", "pre_execution", kind="question", asked=qs, record_id=rid(self.agent_id, tid, "tool"), **common); kind = "ask"
                    elif name in WRITE and mem_scope(str(inp.get("file_path") or "")):
                        written = inp.get("content") or inp.get("new_string") or ""
                        rec = self.base(sid, "Memorizing", ts, "ai", "post_execution", conf=0.8, scope=mem_scope(str(inp.get("file_path"))),
                                        target=file_pointer(self.device, inp.get("file_path"), written), op="add" if name == "Write" else "update",
                                        record_id=rid(self.agent_id, tid, "tool"), **common); kind = "memorize"
                    elif name in PLAN:
                        todos = inp.get("todos") or inp.get("items") or []
                        steps = [{"index": j, "description": "step %d, %d chars" % (j + 1, len(str((td.get("content") if isinstance(td, dict) else td) or "")))} for j, td in enumerate(todos)] if isinstance(todos, list) else []
                        # The text of the plan is the call's input, carried encrypted by a ToolCalling record; the Planning
                        # record that points at it holds only the shape of the plan.
                        call = self.base(sid, "ToolCalling", ts, "ai", "post_execution", tool_meta={"name": name, "call_id": tid, "tool_type": "function"}, input_payload=inp,
                                         effect="write", model_invocation=mi, record_id=rid(self.agent_id, tid, "call"), **common)
                        if up: call["upstream_record_id"] = up
                        out.append(call); prev.append(call["record_id"]); tool_use[tid] = {"rec": call, "kind": "tool", "ts": ts, "inp": inp, "perm": perm, "verify": False, "options": []}
                        rec = self.base(sid, "Planning", ts, "ai", "post_execution", goal="plan via %s, %d steps" % (name, len(steps)),
                                        steps=steps or [{"index": 0, "description": "plan"}], outcome="success", record_id=rid(self.agent_id, tid, "tool"), **common); kind = "plan"
                    else:
                        tt = "mcp" if str(name).startswith("mcp__") else "shell" if name == "Bash" else "skill" if name == "Skill" else "function"
                        tm = {"name": name, "call_id": tid, "tool_type": tt}
                        if tt == "mcp" and "__" in str(name): tm["namespace"] = str(name).split("__")[1]
                        eff = "read" if name in READ else "write" if name in WRITE else "execute" if name == "Bash" else None
                        payload = file_pointer(self.device, inp.get("file_path"), inp.get("content") or inp.get("new_string")) if name in WRITE else inp
                        rec = self.base(sid, "ToolCalling", ts, "ai", "post_execution", tool_meta={a: b for a, b in tm.items() if b}, input_payload=payload,
                                        effect=eff, model_invocation=mi, record_id=rid(self.agent_id, tid, "tool"), **common); kind = "tool"
                    if kind == "plan":
                        rec["upstream_record_id"] = [call["record_id"]]; out.append(rec); prev.append(rec["record_id"]); continue
                    if up: rec["upstream_record_id"] = up
                    out.append(rec)
                    tool_use[tid] = {"rec": rec, "kind": kind, "ts": ts, "inp": inp, "perm": perm, "name": name,
                                     "verify": name == "Bash" and bool(VERIFY.search(str(inp.get("command") or ""))),
                                     "options": [o for o in (opts if name == "AskUserQuestion" else [])]}
        flush_text()
        for tid, tu in tool_use.items():   # calls that never got a result: the turn was interrupted
            if tu.get("kind") == "skip": continue
            rec = tu["rec"]
            if "outcome" not in rec:
                rec["outcome"] = "cancelled"
                if tu["kind"] == "tool": rec["output_payload"] = ""
                if tu["kind"] == "delegate": rec["result"] = ""
        # permission prompts that no tool ever followed: nobody answered
        for pe in perms:
            if pe.get("used") or not sid: continue
            esc = self.base(sid, "Escalating", pe.get("ts"), "ai", "pre_execution", tags=tags_turn, kind="permission", asked={"tool": pe.get("tool_name"), "input": pe.get("tool_input") or {}},
                            outcome="timeout", record_id=rid(self.agent_id, pe.get("tool_use_id") or ("%s/%s" % (pe.get("tool_name"), pe.get("ts"))), "perm"))
            att = self.base(sid, "Attesting", pe.get("ts"), "human", "concurrent", conf=0.6, tags=tags_turn, operator_id="user", gate_kind="permission", disposition="no_response",
                            outcome="timeout", channel="headless", reason="no disposition observed", record_id=rid(self.agent_id, pe.get("tool_use_id") or ("%s/%s" % (pe.get("tool_name"), pe.get("ts"))), "perm-att"))
            att["upstream_record_id"] = [esc["record_id"]]; out.extend([esc, att])
        return out[emitted_from:], info

def strip_none(v):
    if isinstance(v, dict): return {k: strip_none(x) for k, x in v.items() if x is not None}
    if isinstance(v, list): return [strip_none(x) for x in v]
    return v
