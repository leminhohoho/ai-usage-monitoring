# demo

Simulates a small team using coding agents for a work week, through the *real* client and
the *real* API — nothing is faked at the storage layer.

```
# 1. start the server (creates usage.db on first write)
cd projects/ai-usage-monitor && PYTHONPATH=server uv run uvicorn server.app:app --port 9001

# 2. seed three engineers and their API keys
uv run python -c "import sys;sys.path.insert(0,'server');import store;
[store.add_dev('aum_'+n,n,n+'@jobbob.dev') for n in ('alice','bob','carol')]"

# 3. simulate a week
AUM_ENDPOINT=http://127.0.0.1:9001 uv run python demo/simulate.py
```

`repos/` holds three fake repos (`jobbob-frontend`, `jobbob-backend`, `jobbot-ingest`), each
with `ai_usage_client.py` + `.claude/settings.json` + `.env.ai-usage`, so the demo exercises
repo/branch detection and shows what the integration actually looks like in a real repo.

## What the simulation proves

| property | how it shows up |
|---|---|
| offline tolerance | events sit in `demo/spool/<dev>.jsonl` until `sync` succeeds |
| idempotency | replaying an event_id returns `duplicates: 1`, never double-counts |
| auth | a wrong `X-API-Key` gets 401; the body is never trusted for identity |
| redaction | `sk-…`, `gh…`, `AKIA…`, `token=…` and emails are masked at ingest |
| source independence | alice/bob are `claude_code`, carol is `codex` — same schema, same dashboard |
| tool-level detail | `tool.use` events carry `{tool, target, error}` — 117 in the current run |
