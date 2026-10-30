#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stair access: the account's key and the Stair services it reaches (design: Agent Access v0.3).

The owner key ($STAIR_HOME/owner.key) is the account's master credential and is sent only to the ledger and its access
gate. Any other Stair service (the first is share.stair-ai.com) gets a short-lived access token instead, bound to that
one service: this command exchanges the key for it at the gate (RFC 8693 token exchange) and caches it. Nothing here
involves the model; a skill's script calls `stair access token` and reads the token from stdout.

  stair access token --resource https://share.stair-ai.com [--scope share:write] [--fresh]
  stair access me
  stair access admin handle <owner> <handle> [--replace]      operators, with the ledger's administrator token
  stair access admin grant <owner> <resource> <scope>... [--note TEXT]
  stair access admin grants [--owner <owner>] [--resource URL] [--all]
  stair access admin revoke <grant_id>
  stair access admin lookup <owner id | e-mail | handle>

<owner> is an owner id or an e-mail. The administrator token is read from STAIR_ADMIN_TOKEN or --admin-token-file, never
from an argument. Tokens and the gate's address are cached in $STAIR_HOME/access.json, readable by you only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rl_plugin import CHANNEL, HOME, USER_AGENT, api_key, load_config  # noqa: E402

CACHE = HOME / "access.json"
TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
API_KEY_TOKEN_TYPE = "urn:stair:params:oauth:token-type:api-key"
REUSE_SECONDS = 300          # a cached token is handed out while it has at least this long to live
GATE_METADATA_TTL = 86400    # where the gate is, refreshed daily
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class AccessError(Exception):
    """Something the person can act on; printed as one line."""


class NotJSON(AccessError):
    """A server answered with something other than JSON, such as a sign-in page."""


def http(method, url, headers=None, body=None, form=None, timeout=20):
    """(status, parsed JSON) for any answer, including errors; AccessError when the server cannot be reached."""
    sent = {"accept": "application/json", "user-agent": USER_AGENT}
    sent.update(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        sent["content-type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        sent["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=sent)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            if not raw:
                return response.status, None
            try:
                return response.status, json.loads(raw)
            except ValueError:
                raise NotJSON("%s did not answer with JSON (it ended at %s)" % (url, response.geturl()))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"message": raw[:300]}
    except urllib.error.URLError as error:
        raise AccessError("cannot reach %s (%s)" % (url, error.reason))


def problem(body):
    """The server's own words for a refusal."""
    if not isinstance(body, dict):
        return ""
    return body.get("error_description") or body.get("message") or body.get("error") or ""


# ---------------------------------------------------------------------------------------------------------------------
# The account on this machine, the gate, and the token cache
# ---------------------------------------------------------------------------------------------------------------------

def account():
    cfg = load_config()
    if not cfg:
        raise AccessError("this machine has no Stair account yet; run `stair rl setup` first")
    key = api_key(cfg)
    if not key:
        raise AccessError("no owner key on this machine (config.json names none, and STAIR_API_KEY is unset)")
    return cfg, key


def ledger_endpoint(cfg):
    return (cfg.get("endpoint") or CHANNEL["STAIR_DEFAULT_ENDPOINT"]).rstrip("/")


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
        return cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    HOME.mkdir(parents=True, exist_ok=True)
    temporary = CACHE.with_name(CACHE.name + ".tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(str(temporary), str(CACHE))
    os.chmod(str(CACHE), 0o600)


def gate(cfg, cache, refresh=False):
    """The gate's metadata (RFC 8414), found from the ledger this machine writes to, which runs the gate."""
    ledger = ledger_endpoint(cfg)
    known = cache.get("gate")
    if (not refresh and isinstance(known, dict) and known.get("ledger") == ledger
            and time.time() - known.get("fetched_at", 0) < GATE_METADATA_TTL):
        return known
    try:
        status, body = http("GET", ledger + "/.well-known/oauth-authorization-server")
    except NotJSON:
        status, body = 404, None  # a ledger without the gate sends this path to its sign-in page
    if status == 404:
        raise AccessError("the ledger at %s does not run the access gate yet" % ledger)
    if status != 200 or not isinstance(body, dict) or not body.get("token_endpoint") or not body.get("issuer"):
        raise AccessError("the ledger at %s answered %s when asked where its access gate is" % (ledger, status))
    issuer, endpoint = body["issuer"].rstrip("/"), body["token_endpoint"]
    # The owner key will be sent to this endpoint: only when it is the issuer's own and travels encrypted.
    host = urllib.parse.urlsplit(issuer)
    local = host.hostname in ("localhost", "127.0.0.1", "::1")
    if not endpoint.startswith(issuer + "/") or not (host.scheme == "https" or (host.scheme == "http" and local)):
        raise AccessError("the ledger at %s names a token endpoint the key will not be sent to (%s)" % (ledger, endpoint))
    known = {"fetched_at": int(time.time()), "issuer": issuer, "ledger": ledger, "token_endpoint": endpoint}
    cache["gate"] = known
    return known


def canonical_resource(resource):
    """A service as the gate names it: scheme, lower-case host, path without a trailing slash."""
    parts = urllib.parse.urlsplit(resource.strip())
    if parts.scheme not in ("https", "http") or not parts.netloc or parts.query or parts.fragment:
        raise AccessError("--resource must be a service's address, such as https://share.stair-ai.com")
    return "%s://%s%s" % (parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"))


def token(resource, scope=None, fresh=False):
    """An access token for one service: the cached one while it has five minutes left, else a new one from the gate."""
    cfg, key = account()
    resource = canonical_resource(resource)
    cache = load_cache()
    slot = "%s %s" % (resource, scope or "*")
    held = (cache.get("tokens") or {}).get(slot)
    if (not fresh and isinstance(held, dict) and held.get("ledger") == ledger_endpoint(cfg)
            and held.get("expires_at", 0) - time.time() >= REUSE_SECONDS):
        return held["access_token"]
    where = gate(cfg, cache)
    form = {"grant_type": TOKEN_EXCHANGE, "resource": resource, "subject_token": key,
            "subject_token_type": API_KEY_TOKEN_TYPE}
    if scope:
        form["scope"] = scope
    status, body = http("POST", where["token_endpoint"], form=form)
    if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
        error = body.get("error") if isinstance(body, dict) else None
        if error == "invalid_target":
            raise AccessError("%s. Access is given by the Stair administrator; `stair access me` shows the owner id to "
                              "send them" % problem(body).rstrip("."))
        if error == "invalid_request" and "subject_token" in problem(body):
            raise AccessError("the gate does not accept this machine's owner key (%s)" % problem(body))
        raise AccessError("the gate refused (%s): %s" % (error or status, problem(body)))
    cache.setdefault("tokens", {})[slot] = {
        "access_token": body["access_token"],
        "expires_at": int(time.time()) + int(body.get("expires_in") or 3600),
        "ledger": ledger_endpoint(cfg),
        "scope": body.get("scope"),
    }
    save_cache(cache)
    return body["access_token"]


def me():
    cfg, key = account()
    cache = load_cache()
    where = gate(cfg, cache)
    save_cache(cache)
    status, body = http("GET", where["issuer"] + "/access/me", headers={"x-api-key": key})
    if status != 200 or not isinstance(body, dict):
        raise AccessError("the gate answered %s: %s" % (status, problem(body)))
    return body


# ---------------------------------------------------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------------------------------------------------

def admin_token(args):
    value = os.environ.get("STAIR_ADMIN_TOKEN") or os.environ.get("RL_ADMIN_TOKEN") or ""
    if not value and args.admin_token_file:
        with open(os.path.expanduser(args.admin_token_file), encoding="utf-8") as f:
            value = f.read().strip()
    if not value:
        raise AccessError("give --admin-token-file <file holding the administrator token> (or set STAIR_ADMIN_TOKEN)")
    return value


def admin_call(args, method, path, body=None):
    cfg = load_config() or {}
    base = (args.endpoint or ledger_endpoint(cfg)).rstrip("/")
    status, answer = http(method, base + path, headers={"x-admin-token": admin_token(args)}, body=body)
    if status >= 300:
        raise AccessError("the ledger answered %s: %s" % (status, problem(answer)))
    return answer


def find_owner(args, who):
    """An owner view for an owner id, an e-mail or a handle."""
    who = who.strip()
    if UUID.match(who):
        query = {"owner_id": who}
    elif "@" in who:
        query = {"email": who}
    else:
        query = {"handle": who}
    return admin_call(args, "GET", "/v1/admin/owners/lookup?" + urllib.parse.urlencode(query))


def show_owner(view):
    print("owner   %s" % view.get("owner_id"))
    if view.get("email"):
        print("e-mail  %s" % view["email"])
    print("handle  %s" % (view.get("handle") or "(none yet: the administrator gives one)"))
    grants = view.get("grants") or []
    if not grants:
        print("access  (no services yet)")
    for grant in grants:
        print("access  %s  %s" % (grant.get("resource"), " ".join(grant.get("scopes") or [])))


def show_grant(grant):
    state = "revoked" if grant.get("revoked_at") else "live"
    print("%s\t%s\t%s\t%s\t%s\t%s" % (grant.get("grant_id"), state, grant.get("owner_id"), grant.get("resource"),
                                       " ".join(grant.get("scopes") or []), grant.get("note") or ""))


def admin(args):
    if args.admin_cmd == "lookup":
        show_owner(find_owner(args, args.owner))
    elif args.admin_cmd == "handle":
        owner = find_owner(args, args.owner)
        handle = None if args.handle == "-" else args.handle
        show_owner(admin_call(args, "PUT", "/v1/admin/owners/%s/handle" % owner["owner_id"],
                              {"handle": handle, "replace": bool(args.replace)}))
    elif args.admin_cmd == "grant":
        owner = find_owner(args, args.owner)
        body = {"owner_id": owner["owner_id"], "resource": canonical_resource(args.resource), "scopes": args.scopes}
        if args.note:
            body["note"] = args.note
        show_grant(admin_call(args, "POST", "/v1/admin/grants", body))
    elif args.admin_cmd == "grants":
        query = {"state": "all" if args.all else "live"}
        if args.owner:
            query["owner_id"] = find_owner(args, args.owner)["owner_id"]
        if args.resource:
            query["resource"] = canonical_resource(args.resource)
        for grant in admin_call(args, "GET", "/v1/admin/grants?" + urllib.parse.urlencode(query)).get("grants", []):
            show_grant(grant)
    elif args.admin_cmd == "revoke":
        show_grant(admin_call(args, "POST", "/v1/admin/grants/%s/revoke" % args.grant_id))
    else:
        raise AccessError("which admin command? lookup, handle, grant, grants or revoke")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="stair access",
                                     description="The account's key and the Stair services it reaches.")
    commands = parser.add_subparsers(dest="cmd")
    t = commands.add_parser("token", help="print a short-lived access token for one service, for a program to read")
    t.add_argument("--resource", required=True, help="the service, e.g. https://share.stair-ai.com")
    t.add_argument("--scope", default=None, help="narrower than everything granted, e.g. share:write")
    t.add_argument("--fresh", action="store_true", help="ask the gate for a new token even when a cached one is good")
    commands.add_parser("me", help="this account's owner id, handle and the services it may reach")
    operators = argparse.ArgumentParser(add_help=False)
    operators.add_argument("--admin-token-file", default=None, help="file holding the administrator token")
    operators.add_argument("--endpoint", default=None, help="the ledger (default: the configured one)")
    a = commands.add_parser("admin", help="operators: handles and grants, with the ledger's administrator token")
    admin_commands = a.add_subparsers(dest="admin_cmd")
    lookup = admin_commands.add_parser("lookup", parents=[operators], help="an owner, by id, e-mail or handle")
    lookup.add_argument("owner")
    handle = admin_commands.add_parser("handle", parents=[operators],
                                       help="give an owner its handle (- clears it; changing one needs --replace)")
    handle.add_argument("owner")
    handle.add_argument("handle")
    handle.add_argument("--replace", action="store_true")
    grant = admin_commands.add_parser("grant", parents=[operators], help="let an owner get tokens for a service")
    grant.add_argument("owner")
    grant.add_argument("resource")
    grant.add_argument("scopes", nargs="+")
    grant.add_argument("--note", default=None)
    grants = admin_commands.add_parser("grants", parents=[operators], help="list grants (live ones unless --all)")
    grants.add_argument("--owner", default=None)
    grants.add_argument("--resource", default=None)
    grants.add_argument("--all", action="store_true")
    revoke = admin_commands.add_parser("revoke", parents=[operators], help="stop a grant")
    revoke.add_argument("grant_id")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "token":
            value = token(args.resource, args.scope, args.fresh)
            if sys.stdout.isatty():
                print("stair access: this is a credential for %s; let a program read it rather than pasting it"
                      % canonical_resource(args.resource), file=sys.stderr)
            print(value)
            return 0
        if args.cmd == "me":
            show_owner(me())
            return 0
        if args.cmd == "admin":
            return admin(args)
        parser.print_help()
        return 2
    except AccessError as error:
        print("stair access: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
