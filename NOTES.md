# archived 2026-11-20

Status: **complete for its scope** (store + display raw agent sessions, explicit send).
Not running. Nothing here needs a server.

- code: pushed, `github.com/leminhohoho/ai-usage-monitoring` @ `5ed83a7`
- snapshot: `../../archive/ai-usage-monitor-2026-11-20.tar.gz` (incl. the demo DB)
- generated state removed from this tree (demo/repos, spool, usage.db) — recreate with
  `demo/setup_repos.sh` + `demo/simulate.py`

## Where it stopped
Built: client (hook -> spool), explicit `./send-usage.sh`, ingest API (key auth, idempotent,
redaction), dashboard (desktop + mobile, tool calls, search), installer (local + curl).

## What I would do next (ordered)
1. `session_task` table + task_id derived from branch/prompt — the one feature worth adding.
   Never on events; join at read time. Ask only on a miss.
2. Real Claude Code payload check (assistant text on Stop, transcript at SessionEnd).
3. Postgres + retention/redaction policy before any real rollout; consent first.
4. Automate send (SessionEnd hook or cron) once engineers trust the manual flow.
