#!/usr/bin/env python3
"""Simulate a few days of a team using coding agents, and push it through the real client
into the real API. Nothing is faked at the storage layer: this is the same path a hook
on a dev machine would take (spool -> sync -> POST /v1/events)."""
import json
import subprocess, os, random, subprocess, sys, pathlib
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).parent
CLIENT = HERE.parent / "client" / "ai_usage_client.py"
ENDPOINT = os.environ.get("AUM_ENDPOINT", "http://127.0.0.1:9101")
random.seed(7)

DEVS = {
    "alice": {"key": "aum_alice", "repo": "jobbob-frontend", "source": "claude_code", "model": "claude-sonnet-4.5"},
    "bob":   {"key": "aum_bob",   "repo": "jobbob-backend",  "source": "claude_code", "model": "claude-opus-4.1"},
    "carol": {"key": "aum_carol", "repo": "jobbot-ingest",   "source": "codex",        "model": "gpt-5-codex"},
}

TOPICS = [
 ("pagination", "Add an endpoint that returns the weekly job counts per employer, paginated.",
  "I'll look at the endpoint layer first. Changes: 1) add `page`/`per_page` 2) push the "
  "aggregation into SQL so it isn't done in Python 3) cover it with a test."),
 ("docker", "The CI is failing on the docker build step, can you look at why?",
  "The build fails at `RUN apt-get install libpq-dev` — the base image moved upstream. "
  "Pin the base to `python:3.12-slim-bookworm` and it builds again."),
 ("di", "Refactor this service to use dependency injection instead of module-level singletons.",
  "Refactored: `db.py` now takes a session factory through the constructor; the singleton "
  "import is gone and tests inject a fixture instead."),
 ("retry", "Write tests for the retry logic in the ingestion worker.",
  "Added 6 tests around `retry_with_backoff`; two fail because the backoff calls `time.sleep` "
  "directly — I'd inject a sleep function so tests stay fast."),
 ("rerender", "This React component re-renders on every keystroke — find out why and fix it.",
  "It re-renders because `useEffect` recreates the filter object every render, so the "
  "dependency array never matches. Memoise the object with `useMemo`."),
 ("migration", "Explain what this migration does before I run it.",
  "The migration adds a nullable column and backfills in three batches. Safe to run online; "
  "the second index build takes a lock for ~40s, so run it off-peak."),
 ("logging", "Add structured logging with trace ids to the request pipeline.",
  "Added a `trace_id` contextvar injected by middleware, propagated into every log line and "
  "the outbound HTTP headers."),
 ("precommit", "Can you set up a pre-commit hook that runs ruff and mypy?",
  "Set up `.pre-commit-config.yaml` with ruff (fix + format) and mypy on changed files only, "
  "so it stays fast on a big repo."),
 ("403", "Where does the 403 come from on the /jobs/search endpoint?",
  "The auth middleware rejects requests without the `X-Tenant` header; search hits an older "
  "client build that predates the header. I'd make the error body say which header is missing."),
 ("queue", "Draft a plan (no code yet) for moving the ingest pipeline off cron.",
  "Plan only: 1) move ingestion to a queue worker, idempotent by job id 2) keep cron as a "
  "fallback for one sprint 3) add a dashboard on queue lag before removing cron."),
 ("flaky", "This test is flaky in CI but passes locally, how do I debug it?",
  "It's a timezone assumption: the test builds a date with `date.today()` and the CI runner is "
  "UTC. Freeze time in the test with `freezegun` and assert on UTC explicitly."),
 ("perf", "The session history page is slow for employers with many jobs.",
  "N+1: the page loads job rows then queries applications per row. One `GROUP BY` with a join "
  "drops it from 340 queries to 2; measured 1.9s -> 120ms on staged data."),
]

TOOLS = ["Edit", "Read", "Bash", "Grep", "Write"]
TOOL_TARGET = {"Edit": "file_path", "Read": "file_path", "Write": "file_path",
               "Bash": "command", "Grep": "pattern"}
TARGETS = {"file_path": ["src/api/jobs.ts", "server/db.py", "src/components/Filters.tsx",
                         "worker/ingest.py", "migrations/0042_add_company.sql"],
           "command": ["pytest -q", "npm run build", "ruff check .", "docker build ."],
           "pattern": ["retry_with_backoff", "useEffect(", "X-Tenant"]}


def rec(dev, cfg, cwd, when, *args):
    """record one event with an explicit timestamp -> the demo shows a real work week"""
    return run(dev, ["record", *args, "--source", cfg["source"], "--cwd", ".", "--ts", iso(when)], cwd)


def run(dev, args, cwd):
    env = {**os.environ, "AUM_ENDPOINT": ENDPOINT, "AUM_API_KEY": DEVS[dev]["key"],
           "AUM_SPOOL": str(HERE / "spool" / f"{dev}.jsonl")}
    return subprocess.run([sys.executable, str(CLIENT), *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


def iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def main():
    (HERE / "spool").mkdir(exist_ok=True)
    start = (datetime.now(timezone.utc) - timedelta(days=8)).replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = 0
    for day in range(5):
        day0 = start + timedelta(days=day)
        if day0.weekday() >= 5:            # skip the weekend: this is a work week
            continue
        for dev, cfg in DEVS.items():
            for _ in range(random.randint(1, 3)):
                t = day0.replace(hour=random.randint(8, 18), minute=random.randint(0, 59))
                sid = f"sess-{dev}-{sessions:03d}"
                cwd = HERE / "repos" / cfg["repo"]
                rec(dev, cfg, cwd, t, "--type", "session.start", "--session", sid,
                    "--model", cfg["model"])
                topics = random.sample(TOPICS, random.randint(2, 4))
                for name, p, reply in topics:
                    t += timedelta(minutes=random.randint(1, 6))
                    rec(dev, cfg, cwd, t, "--type", "message", "--session", sid, "--role", "user",
                        "--content", p, "--tokens-in", str(random.randint(200, 1400)),
                        "--model", cfg["model"])
                    t += timedelta(minutes=random.randint(1, 4))
                    for tool in random.sample(TOOLS, random.randint(1, 3)):
                        target = random.choice(TARGETS[TOOL_TARGET[tool]])
                        t += timedelta(seconds=random.randint(10, 120))
                        rec(dev, cfg, cwd, t, "--type", "tool.use", "--session", sid,
                            "--content", f"{tool} {target}",
                            "--meta", json.dumps({"tool": tool, "target": target,
                                                  "error": random.random() < 0.08}),
                            "--model", cfg["model"])
                    rec(dev, cfg, cwd, t, "--type", "message", "--session", sid, "--role", "assistant",
                        "--content", reply,
                        "--tokens-in", str(random.randint(1500, 9000)),
                        "--tokens-out", str(random.randint(300, 2500)),
                        "--model", cfg["model"])
                rec(dev, cfg, cwd, t, "--type", "session.end", "--session", sid,
                    "--model", cfg["model"])
                sessions += 1
                if random.random() < 0.5:   # sometimes: the developer is offline, spool waits
                    pass
    print(f"generated {sessions} sessions")
    for dev in DEVS:
        # exactly what an engineer does: run ./send-usage.sh in their repo
        env = {**os.environ, "AUM_ENDPOINT": ENDPOINT, "AUM_API_KEY": DEVS[dev]["key"],
               "AUM_SPOOL": str(HERE / "spool" / f"{dev}.jsonl")}
        r = subprocess.run(["./send-usage.sh"], cwd=HERE / "repos" / DEVS[dev]["repo"],
                           capture_output=True, text=True, env=env)
        print(dev, r.stdout.strip() or r.stderr.strip()[-200:])


if __name__ == "__main__":
    main()
