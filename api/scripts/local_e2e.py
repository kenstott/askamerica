"""Local end-to-end check of the Stripe billing path against the Stripe SANDBOX.

Usage: python local_e2e.py /path/to/.env STRIPE_TEST_SECRET_KEY <step> [args]

The Worker runs under `wrangler dev --local --port 8798` with .dev.vars holding the sandbox key
and STRIPE_WEBHOOK_SECRET=local-e2e-secret. Stripe cannot reach localhost, so each step replays
the real events Stripe recorded, signed with the local secret: the payloads are Stripe's own.

Steps:
  checkout <api key>            print the Starter checkout URL the Worker minted
  replay <subscription id>      deliver that subscription's recorded events to the local Worker
  latest-sub <user id>          print the newest sandbox subscription carrying this user_id
  cancel <subscription id>      cancel the subscription now (Stripe then records the deletion)
  quota <api key>               print the Worker's view of the plan
"""

import hashlib
import hmac
import json
import sys
import time

import httpx

API = "https://api.stripe.com/v1"
LOCAL = "http://localhost:8798"
LOCAL_SECRET = "local-e2e-secret"


def read_key(env_path: str, name: str) -> str:
    for line in open(env_path, encoding="utf-8"):
        if line.startswith(f"{name}="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if "_test_" not in key:
                sys.exit("refusing: this script only runs against the sandbox")
            return key
    sys.exit(f"{name} not found in the env file.")


def main() -> None:
    key = read_key(sys.argv[1], sys.argv[2])
    step, args = sys.argv[3], sys.argv[4:]
    with httpx.Client(timeout=30) as c:
        if step == "checkout":
            r = c.get(f"{LOCAL}/v1/checkout", headers={"X-API-Key": args[0]})
            print(r.status_code, json.dumps({k: v for k, v in r.json().items() if k != "prepaid"})[:160])
            if r.status_code == 200:
                json.dump({"pay": {"url": r.json()["starter"]["checkout_url"]}},
                          open(args[1], "w", encoding="utf-8"))
        elif step == "quota":
            r = c.get(f"{LOCAL}/v1/quota", headers={"X-API-Key": args[0]})
            q = r.json()
            print(r.status_code, {k: q.get(k) for k in ("tier", "limit_bytes", "used_bytes")})
        elif step == "latest-sub":
            subs = c.get(f"{API}/subscriptions?limit=20&status=all", auth=(key, "")).json()["data"]
            mine = [s for s in subs if s["metadata"].get("user_id") == args[0]]
            for s in mine[:1]:
                print(s["id"], s["status"], s["items"]["data"][0]["price"]["id"],
                      "managed:", s.get("managed_payments"))
            if not mine:
                print("none")
        elif step == "cancel":
            r = c.delete(f"{API}/subscriptions/{args[0]}", auth=(key, ""))
            print(r.status_code, r.json().get("status"))
        elif step == "replay":
            events = c.get(f"{API}/events?limit=100", auth=(key, "")).json()["data"]
            mine = [e for e in events if e["type"].startswith("customer.subscription.")
                    and e["data"]["object"].get("id") == args[0]]
            for e in sorted(mine, key=lambda e: e["created"]):
                body = json.dumps(e)
                t = int(time.time())
                sig = hmac.new(LOCAL_SECRET.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
                r = c.post(f"{LOCAL}/v1/webhooks/stripe", content=body,
                           headers={"Stripe-Signature": f"t={t},v1={sig}",
                                    "Content-Type": "application/json"})
                print(e["type"], e["data"]["object"]["status"], "->", r.status_code, r.text)
            if not mine:
                print("no events recorded for", args[0])
        else:
            sys.exit(f"unknown step {step}")


if __name__ == "__main__":
    main()
