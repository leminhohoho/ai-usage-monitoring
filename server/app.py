"""AI usage monitor - ingest API + dashboard.

  POST /v1/events   batched canonical events, X-API-Key auth, idempotent per event_id
  GET  /            dashboard (Claude-ish light UI)
  GET  /api/*       queries used by the dashboard
"""
import json, os, re, pathlib
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import store

app = FastAPI(title="AI usage monitor")
HERE = pathlib.Path(__file__).parent

# --- redaction: run at ingest so raw content never lands in the DB with secrets in it -----
SECRET_PATTERNS = [
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})"), "sk-***"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})"), "gh***"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "AKIA***"),
    (re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[\"'']?([^\s\"'`,;]{8,})"), r"\1=***"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
]

def redact(s):
    if not s:
        return s
    for pat, repl in SECRET_PATTERNS:
        s = pat.sub(repl, s)
    return s

@app.post("/v1/events")
async def ingest(req: Request, x_api_key: str = Header(default="")):
    dev = store.dev_for_key(x_api_key)
    if not dev:
        raise HTTPException(401, "unknown api key")
    body = await req.json()
    raw = body.get("events", [])
    rows = []
    for e in raw:
        try:
            rows.append(dict(
                event_id=str(e["event_id"]), ts=str(e["ts"]), dev=dev,
                source=str(e.get("source", "unknown")), session_id=str(e["session_id"]),
                event_type=str(e.get("event_type", "message")), role=e.get("role"),
                model=e.get("model"), tokens_in=int(e.get("tokens_in") or 0),
                tokens_out=int(e.get("tokens_out") or 0), repo=e.get("repo"),
                branch=e.get("branch"), content=redact(e.get("content")),
                meta=json.dumps(e.get("meta") or {}),
            ))
        except KeyError:
            continue
    accepted, dup = store.insert_events(rows)
    return {"accepted": accepted, "duplicates": dup}

@app.get("/api/sessions")
def api_sessions(dev: str = None, source: str = None, q: str = None, limit: int = 40, offset: int = 0):
    return store.sessions(dev, source, q, limit, offset)

@app.get("/api/session/{sid}")
def api_session(sid: str):
    return {"session_id": sid, "events": store.session_detail(sid)}

@app.get("/api/stats")
def api_stats():
    return store.stats()

@app.get("/api/devs")
def api_devs():
    with store.conn() as c:
        return [dict(r) for r in c.execute("SELECT dev,email FROM devs ORDER BY dev")]

@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "ui.html").read_text()
