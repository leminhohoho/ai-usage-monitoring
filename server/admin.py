"""Create devs / API keys.  uv run python projects/ai-usage-monitor/server/admin.py add alice a@x.dev"""
import sys, secrets, store

if __name__ == "__main__":
    if sys.argv[1] == "add":
        key = sys.argv[4] if len(sys.argv) > 4 else "aum_" + secrets.token_urlsafe(24)
        store.add_dev(key, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        print(key)
    elif sys.argv[1] == "list":
        with store.conn() as c:
            for r in c.execute("SELECT dev,email,api_key FROM devs"):
                print(r["dev"], r["email"], r["api_key"])
