# ai-usage-monitor

Collect **raw AI coding-agent sessions per engineer** and show them in a dashboard.
Scope for now: store + display only. No task monitoring, no evaluation, no scoring.

## Architecture (deliberately three small pieces)

```
dev machine                      monitor server                    browser
-----------                      --------------                    -------
ai_usage_client.py   spool.jsonl   POST /v1/events   SQLite    GET /   dashboard
(Claude Code hooks)  ---------->   (api key,           events          (sessions,
                                   idempotent,         table           conversation,
                                   redacted)                           search)
```

- **client** `client/ai_usage_client.py` — stdlib only, dropped into each repo. Writes to a
  local JSONL spool first, so losing the network loses nothing. **Nothing is sent
  automatically**: the engineer runs `./send-usage.sh` when they want to push.
- **server** `server/app.py` — FastAPI. Auth by API key (a key maps to a person, so identity
  never comes from the request body), idempotent on `event_id`, redacts secrets/PII at ingest.
- **store** `server/store.py` — SQLite, append-only `events`. Sessions and aggregates are
  derived views recomputed from events, so the raw record is never overwritten.
- **dashboard** `server/ui.html` — per-person totals + session list + full conversation reader
  + search inside the raw text.

## Run it

```bash
cd projects/ai-usage-monitor
PYTHONPATH=server uv run uvicorn server.app:app --host 0.0.0.0 --port 9001
```

Dashboard: https://ubuntu.taila0f05e.ts.net:9001/ · demo data + how it's generated: `demo/README.md`

## Decisions

- **Identity from the API key, not the payload.** A dev machine can lie about anything except
  which key it holds.
- **Store raw, derive everything else.** If the definition of "usage" changes, I don't need to
  re-collect — the events are still there.
- **Redact at ingest, not at read.** Secrets shouldn't be one SQL query away.
- **SQLite for now.** One team's sessions are tiny; Postgres is a migration, not a redesign.

## Open (real-world) questions

1. Where do the API keys live, and who can rotate them?
2. Is storing raw conversation text acceptable to the team? (Consent — this is the part that
   decides whether the tool is observability or surveillance.)
3. Does the client run from a Claude Code hook, or does someone prefer a nightly export?
4. Retention: how long is raw text kept?


## Delivery model (how events reach the server)

| step | who | network? |
|---|---|---|
| hook fires | Claude Code | no — appends one line to `.ai-usage/spool.jsonl` (~2 ms) |
| sync | background child of the hook, + SessionEnd, + a 5-min catch-up timer | yes, batched, retried |
| ingest | `POST /v1/events` with `X-API-Key` → dev | — |

The hot path never blocks on the network. If the machine is offline the spool keeps growing
and the next sync drains it; `event_id` makes replays harmless.

## Sending (explicit, for now)

```bash
cd <your repo>
./send-usage.sh            # push everything currently spooled
./send-usage.sh --status   # how many events are waiting, and where they go
./send-usage.sh --dry-run  # what would be sent
```

Config lives in `.env.ai-usage` next to the script (git-ignored; see
`client/env.ai-usage.example`). Re-sending is harmless — events carry an `event_id` and the
server dedupes — and a failed send never loses anything, the spool is only truncated after a
successful POST.

Automating this later is a one-line change: a `SessionEnd` hook calling `send-usage.sh`, or a
five-minute cron. Deliberately not done yet, so the data flow stays obvious while the tool is
being reviewed.
