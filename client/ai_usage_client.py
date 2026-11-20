#!/usr/bin/env python3
"""ai_usage_client.py - drop this into a repo (or into ~/.local/bin) to report AI agent usage.

Zero dependencies (stdlib only), so it runs anywhere the engineers already have python.

  export AUM_ENDPOINT=https://monitor.internal
  export AUM_API_KEY=aum_xxx
  export AUM_DEV=alice                 # who I am
  python ai_usage_client.py sync             # drain the local spool
  python ai_usage_client.py hook <json>      # Claude Code / Codex hook entry point
  python ai_usage_client.py record --type session.start --session s1 ...

Design notes:
  * the spool is a local append-only JSONL file -> survives network loss, no data lost;
  * the API key decides who you are server-side; AUM_DEV is only a hint for local labels;
  * batching + idempotent event_ids, so retries never double-count.
"""
import argparse, json, os, pathlib, sys, uuid, urllib.request, urllib.error
from datetime import datetime, timezone

SPOOL = pathlib.Path(os.environ.get("AUM_SPOOL", pathlib.Path.home() / ".ai-usage" / "spool.jsonl"))
ENDPOINT = os.environ.get("AUM_ENDPOINT", "http://127.0.0.1:9100").rstrip("/")
API_KEY = os.environ.get("AUM_API_KEY", "")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def repo_info(cwd="."):
    d = pathlib.Path(cwd).resolve()
    for p in [d, *d.parents]:
        if (p / ".git").exists():
            branch = None
            try:
                head = (p / ".git" / "HEAD").read_text().strip()
                branch = head.split("/")[-1] if head.startswith("ref:") else head[:8]
            except OSError:
                pass
            return p.name, branch
    return None, None


def record(kind, session, role=None, content=None, model=None, tokens_in=0, tokens_out=0,
           source="claude_code", meta=None, cwd=".", event_id=None, ts=None):
    repo, branch = repo_info(cwd)
    ev = {"event_id": event_id or str(uuid.uuid4()), "ts": ts or now(), "source": source,
          "session_id": session, "event_type": kind, "role": role, "model": model,
          "tokens_in": int(tokens_in or 0), "tokens_out": int(tokens_out or 0),
          "repo": repo, "branch": branch, "content": content, "meta": meta or {}}
    SPOOL.parent.mkdir(parents=True, exist_ok=True)
    with SPOOL.open("a") as f:
        f.write(json.dumps(ev) + "\n")
    return ev


def sync(batch=200):
    if not SPOOL.exists():
        print("nothing spooled")
        return
    lines = [l for l in SPOOL.read_text().splitlines() if l.strip()]
    if not lines:
        print("nothing spooled")
        return
    sent, left = 0, []
    for i in range(0, len(lines), batch):
        chunk = lines[i:i + batch]
        body = json.dumps({"events": [json.loads(c) for c in chunk]}).encode()
        req = urllib.request.Request(ENDPOINT + "/v1/events", data=body,
                                     headers={"Content-Type": "application/json",
                                              "X-API-Key": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.loads(r.read())
                sent += len(chunk)
                print(f"sent {len(chunk)} -> {res}")
        except (urllib.error.URLError, OSError) as e:
            left.extend(chunk)          # keep everything unsent; retry later
            print("offline, keeping spool:", e)
    SPOOL.write_text("".join(l + "\n" for l in left))
    print(f"spooled: {len(left)} remaining")


TOOL_TARGET = {"Edit": "file_path", "Write": "file_path", "Read": "file_path",
               "Bash": "command", "Grep": "pattern", "Glob": "pattern", "WebFetch": "url"}


def hook(payload_json):
    """Claude Code hooks hand us JSON on stdin, e.g.
    {"hook_event_name":"PostToolUse","session_id":"...","tool_name":"Edit",
     "tool_input":{"file_path":"src/x.ts"},"tool_response":{...},"cwd":"."}
    """
    p = json.loads(payload_json)
    name = p.get("hook_event_name")
    sid = p.get("session_id", "unknown")
    meta, content, kind, role = {}, None, "message", None

    if name == "SessionStart":
        kind = "session.start"
        meta["model"] = p.get("model")
    elif name == "SessionEnd":
        kind = "session.end"
        meta["reason"] = p.get("reason")
    elif name == "UserPromptSubmit":
        kind, role, content = "message", "user", p.get("prompt")
    elif name == "Stop":
        # assistant turn finished; the transcript has the reply
        kind, role = "message", "assistant"
        content = p.get("last_assistant_message")
    elif name in ("PostToolUse", "PreToolUse"):
        kind = "tool.use" if name == "PostToolUse" else "tool.start"
        tool = p.get("tool_name", "?")
        tin = p.get("tool_input") or {}
        target = tin.get(TOOL_TARGET.get(tool, ""), "")
        meta = {"tool": tool, "target": target,
                "error": bool((p.get("tool_response") or {}).get("is_error"))}
        content = f"{tool} {target}".strip()
    elif name == "Notification":
        kind, content = "notification", p.get("message")

    record(kind, session=sid, role=role, content=content,
           model=p.get("model"), meta=meta, cwd=p.get("cwd", "."),
           tokens_in=p.get("tokens_in", 0), tokens_out=p.get("tokens_out", 0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    h = sub.add_parser("hook"); h.add_argument("payload", nargs="?", default=None)
    r = sub.add_parser("record")
    for a in ["--type", "--session", "--role", "--content", "--model"]:
        r.add_argument(a, default=None)
    r.add_argument("--tokens-in", type=int, default=0)
    r.add_argument("--tokens-out", type=int, default=0)
    r.add_argument("--source", default="claude_code")
    r.add_argument("--cwd", default=".")
    r.add_argument("--ts", default=None)
    r.add_argument("--meta", default=None)
    a = ap.parse_args()
    if a.cmd == "sync":
        sync()
    elif a.cmd == "hook":
        hook(a.payload if a.payload is not None else sys.stdin.read())
        # deliberately NO sync here: the hook only records. Draining the spool is the
        # engineer's explicit action for now -> ./send-usage.sh
    else:
        record(a.type or "message", a.session or str(uuid.uuid4()), a.role, a.content, a.model,
               a.tokens_in, a.tokens_out, a.source, meta=json.loads(a.meta) if a.meta else None,
               cwd=a.cwd, ts=a.ts)
        print("spooled")
