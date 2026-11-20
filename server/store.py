"""Storage for the AI usage monitor: append-only canonical events in SQLite.

Design rule (borrowed from the colleague's proposal): store what was observed, never
interpretation. Sessions/aggregates are *derived views*, recomputed from events.
"""
import json, sqlite3, os, pathlib

DB = pathlib.Path(os.environ.get("AUM_DB", pathlib.Path(__file__).parent.parent / "usage.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS devs (
  api_key TEXT PRIMARY KEY,
  dev     TEXT NOT NULL,
  email   TEXT,
  created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS events (
  event_id   TEXT PRIMARY KEY,          -- idempotency: replays are free
  ts         TEXT NOT NULL,             -- ISO-8601 UTC
  dev        TEXT NOT NULL,             -- resolved from the api key, never trusted from body
  source     TEXT NOT NULL,             -- claude_code | codex | other
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,             -- session.start | message | tool.use | session.end
  role       TEXT,                      -- user | assistant
  model      TEXT,
  tokens_in  INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  repo       TEXT,
  branch     TEXT,
  content    TEXT,                      -- raw conversation text (redacted at ingest)
  meta       TEXT,                      -- JSON blob for source-specific fields
  received   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_dev_ts  ON events(dev, ts);
"""


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def add_dev(key, dev, email=None):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO devs(api_key, dev, email) VALUES (?,?,?)", (key, dev, email))


def dev_for_key(key):
    with conn() as c:
        r = c.execute("SELECT dev FROM devs WHERE api_key=?", (key,)).fetchone()
    return r["dev"] if r else None


def insert_events(events):
    """Returns (accepted, duplicates)."""
    accepted = dup = 0
    with conn() as c:
        for e in events:
            try:
                c.execute(
                    """INSERT INTO events(event_id, ts, dev, source, session_id, event_type, role,
                                         model, tokens_in, tokens_out, repo, branch, content, meta)
                       VALUES (:event_id,:ts,:dev,:source,:session_id,:event_type,:role,
                               :model,:tokens_in,:tokens_out,:repo,:branch,:content,:meta)""", e)
                accepted += 1
            except sqlite3.IntegrityError:
                dup += 1
    return accepted, dup


SESSIONS_SQL = """
SELECT s.session_id, s.dev, s.source, MIN(s.ts) AS started, MAX(s.ts) AS ended,
       COUNT(*) FILTER (WHERE s.event_type='message') AS messages,
       COUNT(*) FILTER (WHERE s.event_type='tool.use') AS tools,
       COUNT(*) FILTER (WHERE s.event_type='tool.use' AND s.meta LIKE '%"error": true%') AS tool_errors,
       SUM(s.tokens_in) AS tokens_in, SUM(s.tokens_out) AS tokens_out,
       COALESCE(MAX(s.repo),'') AS repo, COALESCE(MAX(s.model),'') AS model,
       MIN(s.branch) AS branch,
       COALESCE((SELECT content FROM events e2 WHERE e2.session_id=s.session_id
                 AND e2.event_type='message' AND e2.role='user' AND content IS NOT NULL
                 ORDER BY e2.ts LIMIT 1),'') AS first_prompt
FROM events s
WHERE {where}
GROUP BY s.session_id
ORDER BY ended DESC
LIMIT ? OFFSET ?
"""


def sessions(dev=None, source=None, q=None, limit=50, offset=0):
    where, args = ["1=1"], []
    if dev:
        where.append("s.dev=?"); args.append(dev)
    if source:
        where.append("s.source=?"); args.append(source)
    if q:
        where.append("s.session_id IN (SELECT session_id FROM events WHERE content LIKE ?)")
        args.append(f"%{q}%")
    sql = SESSIONS_SQL.format(where=" AND ".join(where))
    with conn() as c:
        return [dict(r) for r in c.execute(sql, (*args, limit, offset))]


def session_detail(sid):
    with conn() as c:
        ev = [dict(r) for r in c.execute(
            "SELECT ts,event_type,role,model,tokens_in,tokens_out,repo,branch,content,meta "
            "FROM events WHERE session_id=? ORDER BY ts, rowid", (sid,))]
    return ev


def stats():
    with conn() as c:
        per_dev = [dict(r) for r in c.execute("""
            SELECT dev, COUNT(DISTINCT session_id) AS sessions, COUNT(*) AS events,
                   SUM(tokens_in+tokens_out) AS tokens,
                   COUNT(DISTINCT date(ts)) AS active_days, MAX(ts) AS last_seen
            FROM events GROUP BY dev ORDER BY tokens DESC""")]
        per_day = [dict(r) for r in c.execute("""
            SELECT date(ts) AS day, dev, COUNT(DISTINCT session_id) AS sessions,
                   SUM(tokens_in+tokens_out) AS tokens
            FROM events GROUP BY day, dev ORDER BY day""")]
        by_source = [dict(r) for r in c.execute(
            "SELECT source, COUNT(DISTINCT session_id) AS n FROM events GROUP BY source")]
    return {"per_dev": per_dev, "per_day": per_day, "by_source": by_source}
