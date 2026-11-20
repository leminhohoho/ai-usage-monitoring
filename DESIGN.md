# AI usage monitor — condensed design

Collect **raw AI coding-agent sessions per engineer** and show them in a dashboard. Scope was
deliberately: store + display. No task management, no evaluation, no scoring.

## The three pieces

```
dev machine                    monitor server                  browser
ai_usage_client.py   spool      POST /v1/events   sqlite      GET /  dashboard
(agent hooks)      -------->    api key -> dev    events      (people, sessions,
                   jsonl        idempotent        table       conversations, search)
```

### Client — one file, stdlib only

- `record(...)` appends one JSON line to a local spool. **No network in the hot path.**
- `hook(payload)` maps agent hook payloads to events and calls `record`.
- `sync()` batches the spool to `POST /v1/events`, and only truncates the spool after a
  successful response. Offline runs leave the spool intact.
- `send-usage.sh` wraps `sync` with `.env.ai-usage` loading, `--status`, `--dry-run`.
- `install.sh` works from a checkout *or* piped from curl, merges (never clobbers) the agent's
  hook config, writes `.env.ai-usage` with `chmod 600`, and gitignores secrets.

Event shape: `event_id, ts, source, session_id, event_type, role, model, tokens_in,
tokens_out, repo, branch, content, meta`. Types: `session.start`, `message`, `tool.use`,
`session.end`. Tool events carry `{tool, target, error}` — extract them from the agent payload,
they are the most interesting part of the data.

### Server — FastAPI + sqlite

- `POST /v1/events`: API key → person (identity from the key, never from the payload),
  dedupe on `event_id`, **redact secrets and emails at ingest** (`sk-…`, `token=…`, emails),
  insert.
- `GET /api/stats | /api/sessions | /api/session/{id} | /api/search`.
- Admin script to add a person and mint a key.

### Dashboard — one HTML file

People totals, sessions table (msgs · tools · errors · tokens · first prompt), conversation
reader with tool calls inline and errors highlighted, full-text search over raw text.

## Decisions worth keeping

1. **Identity comes from the API key**, not from a `dev` field. Anything else is spoofable.
2. **Raw text is stored**, and the dashboard is a reader. Derived metrics are computed on read,
   so the schema does not have to predict the questions.
3. **`task_id` never goes on events.** Events are append-only observations; attribution is a
   separate mutable `session_task` row joined at read time. That way an answer arriving at
   10:11 retroactively attributes everything from 10:01, and sessions can be re-attributed or
   split later. Immutable = observation, mutable = interpretation.
4. **Derive the task, don't ask for it.** Most developers already name branches
   `feature/JOB-42-…`; regex it out of the branch, fall back to the first prompt, and let manual
   override handle the rest. A prompt at session start taxes attention exactly when the
   developer has the least information and the least patience, and it trains the dismiss reflex.
   Automate the common case, ask only on a miss, never block work, and allow "unassigned".
5. **Explicit send beats automation while you are earning trust.** One command, visible data
   flow, nothing leaves the machine until a human runs it. Automating later is one line
   (`SessionEnd` hook or cron); un-shipping an invasive default is much harder.
6. **The demo is the test suite.** Drive the real client and the real API with simulated events
   so offline spooling, idempotent replay, 401 on a bad key, and redaction are all exercised
   continuously.

## Things that bit, and the fix

- **Blocking hook.** `hook()` used to call `sync()` inline: a 20-second network timeout inside
  the agent's turn on every prompt and every tool call. Fix: record only; send is explicit (or
  a detached child / timer).
- **Tool calls invisible.** Reported as "no tool logs" — two bugs: the simulator never emitted
  `tool.use`, and the dashboard filtered those events out. Check the data before the UI.
- **Fixed-width reading pane** made the mobile list unusable. Stack, don't squeeze.
- **Fake `.git` directories** in demo repos. Use `git init` or generate them from a script and
  gitignore them.
- **`curl | bash` is unattested.** Point at a tag, or publish `SHA256SUMS`, or tell people to
  clone. The installer here is 150 lines that copy files and write JSON — the habit matters for
  the next one.

## Ethics (write this down before rollout)

Raw conversation text is a different category from token counts. Consent and retention policy
come before the dashboard, not after: who can read whose prompts, how long it is kept, and what
it is explicitly *not* used for (performance reviews). If the team discovers it afterwards, the
tool is dead regardless of quality.
