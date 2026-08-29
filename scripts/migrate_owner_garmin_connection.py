"""
One-time migration: move the owner's existing GARTH_TOKEN into the new
per-user garmin_connections table, so the switch to per-user Garmin accounts
doesn't require the owner to reconnect/re-login. Run this once, after:

  1. server/sql/garmin_connections.sql has been applied in the Supabase SQL
     editor.
  2. GARMIN_TOKEN_ENCRYPTION_KEY, SUPABASE_SERVICE_ROLE_KEY are set (locally
     for this script, and on Vercel for the backend - same values).

Needs, interactively or via scripts/.env.garmin-style env vars:
  - the owner's Supabase user id (Supabase dashboard -> Authentication ->
    Users -> find the row by the owner's Google email -> copy the UUID)
  - GARMIN_TOKEN_ENCRYPTION_KEY (base64, same value set on Vercel)
  - SUPABASE_SERVICE_ROLE_KEY (Supabase dashboard -> Settings -> API)

Reads the existing token from server/.env.garth_token (written by
scripts/generate_token.py) - no Garmin login needed, this just re-homes the
token that's already working today.
"""

import base64
import os
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SUPABASE_URL = "https://qvbdnaeewytfoolmubch.supabase.co"

token_file = Path(__file__).resolve().parent.parent / "server" / ".env.garth_token"
if not token_file.exists():
    raise SystemExit(f"{token_file} not found - run scripts/generate_token.py first.")
token = token_file.read_text().strip()

user_id = os.environ.get("OWNER_USER_ID") or input("Owner's Supabase user id (uuid): ").strip()
enc_key_b64 = os.environ.get("GARMIN_TOKEN_ENCRYPTION_KEY") or input("GARMIN_TOKEN_ENCRYPTION_KEY: ").strip()
service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or input("SUPABASE_SERVICE_ROLE_KEY: ").strip()

key = base64.b64decode(enc_key_b64)
nonce = os.urandom(12)
ct = AESGCM(key).encrypt(nonce, token.encode("utf-8"), None)
encrypted_token = base64.b64encode(nonce + ct).decode("ascii")

r = httpx.post(
    f"{SUPABASE_URL}/rest/v1/garmin_connections?on_conflict=user_id",
    headers={
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    },
    json={"user_id": user_id, "encrypted_token": encrypted_token, "status": "connected"},
    timeout=10.0,
)
r.raise_for_status()
print("Migrated. garmin_connections row:", r.json())
