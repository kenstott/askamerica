"""Create AskAmerica's Stripe plans and webhook endpoint in one Stripe mode (sandbox or live).

Usage: python stripe_setup.py /path/to/.env KEY_NAME /path/to/webhook-secret-out

Reads the named Stripe key from the env file. Finds each object by its metadata before creating
it, so a second run reports what exists. Prints the price ids for wrangler.toml. The webhook
signing secret is shown by Stripe only at creation: it is written to the output file (never
printed) for `wrangler secret put STRIPE_WEBHOOK_SECRET < file`.
"""

import sys

import httpx

API = "https://api.stripe.com/v1"
WEBHOOK_URL = "https://api.askamerica.ai/v1/webhooks/stripe"
EVENTS = [
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "checkout.session.completed",
    "charge.refunded",
]
PLANS = {
    "starter": ("AskAmerica Starter", "50 GB of data scanned per month.", 1900),
    "pro": ("AskAmerica Pro", "500 GB of data scanned per month.", 9900),
}


def read_key(env_path: str, name: str) -> str:
    for line in open(env_path, encoding="utf-8"):
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{name} not found in the env file.")


def call(c: httpx.Client, method: str, path: str, data: dict | None = None) -> dict:
    resp = c.request(method, f"{API}{path}", data=data)
    body = resp.json()
    if resp.status_code >= 400:
        err = body.get("error", {})
        sys.exit(f"FAIL {method} {path} -> {resp.status_code}: {err.get('code')} | "
                 f"{err.get('param')} | {err.get('message')}")
    return body


def main() -> None:
    key = read_key(sys.argv[1], sys.argv[2])
    secret_out = sys.argv[3]
    print("mode:", "LIVE" if "_live_" in key else "sandbox")
    with httpx.Client(auth=(key, ""), timeout=30) as c:
        products = call(c, "GET", "/products?active=true&limit=100")["data"]
        for plan, (name, description, cents) in PLANS.items():
            sku = f"askamerica-{plan}"
            mine = [p for p in products if p["metadata"].get("sku") == sku]
            product = mine[0] if mine else call(c, "POST", "/products", {
                "name": name,
                "description": description,
                "tax_code": "txcd_10103001",  # Software as a service, business use
                "metadata[sku]": sku,
            })
            prices = call(c, "GET", f"/prices?product={product['id']}&active=true")["data"]
            price = prices[0] if prices else call(c, "POST", "/prices", {
                "product": product["id"],
                "currency": "usd",
                "unit_amount": str(cents),
                "recurring[interval]": "month",
            })
            assert price["unit_amount"] == cents and price["recurring"]["interval"] == "month", price
            print(f"STRIPE_PRICE_{plan.upper()} = \"{price['id']}\""
                  f"   ({'existing' if prices else 'created'}, product {product['id']})")

        hooks = call(c, "GET", "/webhook_endpoints?limit=100")["data"]
        mine = [h for h in hooks if h["url"] == WEBHOOK_URL and h["status"] == "enabled"]
        if mine:
            print("webhook endpoint exists:", mine[0]["id"],
                  "(its secret is not readable again; delete the endpoint and rerun to mint a new one)")
        else:
            data = {"url": WEBHOOK_URL, "description": "AskAmerica plan lifecycle"}
            for i, ev in enumerate(EVENTS):
                data[f"enabled_events[{i}]"] = ev
            hook = call(c, "POST", "/webhook_endpoints", data)
            with open(secret_out, "w", encoding="utf-8") as fh:
                fh.write(hook["secret"])
            print("webhook endpoint created:", hook["id"], "| secret written to", secret_out)


if __name__ == "__main__":
    main()
