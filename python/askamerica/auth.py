import getpass
import requests
from typing import Optional
from .config import API_BASE_URL, save_config
from .exceptions import AuthError


def login(email: Optional[str] = None) -> str:
    if email is None:
        email = input("Email: ").strip()

    r = requests.post(f"{API_BASE_URL}/v1/auth/request-otp", json={"email": email})
    if not r.ok:
        raise AuthError(f"Failed to send OTP: {r.text}")

    print(f"A 6-digit code has been sent to {email}.")
    code = getpass.getpass("Enter code: ").strip()

    r = requests.post(f"{API_BASE_URL}/v1/auth/verify-otp", json={"email": email, "code": code})
    if not r.ok:
        data = r.json()
        raise AuthError(data.get("error", "verification failed"))

    data = r.json()
    api_key = data["api_key"]
    save_config({"api_key": api_key, "email": email, "tier": data["tier"]})
    print(f"Logged in. API key saved to ~/.askamerica/config.json")
    print(f"Tier: {data['tier']} — {data['quota_gb']} GB/month")
    return api_key
