"""
Per-user Garmin connections (Supabase-backed), replacing the single global
GARTH_TOKEN. See CLAUDE.md's "Garmin auth" section for the model.

Auth: every route that touches Garmin data requires an
`Authorization: Bearer <supabase access token>` header. verify_user() asks
Supabase's own auth server to validate it - this works regardless of whether
the project signs sessions with a shared JWT secret or the newer JWKS scheme,
so there's no signing secret to manage locally - and returns the caller's
Supabase user id, the primary key into garmin_connections.

The Garmin token itself is encrypted at rest (AES-256-GCM) before being
stored, and all garmin_connections reads/writes go through Supabase's
PostgREST API using the service-role key (bypasses RLS - the frontend never
talks to this table directly, unlike user_data).
"""

import base64
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from garminconnect import Garmin, GarminConnectAuthenticationError

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://qvbdnaeewytfoolmubch.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


class NeedsReauth(Exception):
    """No working Garmin connection for this user - caller should surface a
    "connect your Garmin account" prompt, not a generic error."""


def _encryption_key() -> bytes:
    raw = os.environ.get("GARMIN_TOKEN_ENCRYPTION_KEY")
    if not raw:
        raise HTTPException(500, "GARMIN_TOKEN_ENCRYPTION_KEY env var is not set on the server")
    return base64.b64decode(raw)


def encrypt_token(token: str) -> str:
    """AES-256-GCM encrypt; returns base64(nonce || ciphertext) for storage
    as plain text (stored as a `text` column, not `bytea`, so PostgREST
    doesn't need Postgres's bytea hex-escape wire format)."""
    key = _encryption_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, token.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_token(blob_b64: str) -> str:
    key = _encryption_key()
    raw = base64.b64decode(blob_b64)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")


def verify_user(authorization: Optional[str]) -> str:
    """Validate a Supabase access token, return the caller's user id (uuid)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not SUPABASE_ANON_KEY:
        raise HTTPException(500, "SUPABASE_ANON_KEY env var is not set on the server")
    try:
        r = httpx.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"could not reach Supabase auth: {e}")
    if r.status_code != 200:
        raise HTTPException(401, "invalid or expired session")
    return r.json()["id"]


def _pgrest(method: str, path: str, **kw) -> httpx.Response:
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(500, "SUPABASE_SERVICE_ROLE_KEY env var is not set on the server")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    headers.update(kw.pop("headers", {}))
    return httpx.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=headers, timeout=10.0, **kw)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(user_id: str) -> Optional[dict]:
    uid = urllib.parse.quote(user_id, safe="")
    r = _pgrest("GET", f"garmin_connections?user_id=eq.{uid}&select=*")
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def save_connection(user_id: str, token: str, garmin_email: Optional[str] = None) -> None:
    body = {
        "user_id": user_id,
        "encrypted_token": encrypt_token(token),
        "status": "connected",
        "last_auth_at": _now(),
    }
    if garmin_email:
        body["garmin_email"] = garmin_email
    r = _pgrest(
        "POST", "garmin_connections?on_conflict=user_id",
        headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        json=body,
    )
    r.raise_for_status()


def mark_needs_reauth(user_id: str) -> None:
    uid = urllib.parse.quote(user_id, safe="")
    r = _pgrest("PATCH", f"garmin_connections?user_id=eq.{uid}", json={"status": "needs_reauth"})
    r.raise_for_status()


def mark_synced(user_id: str) -> None:
    uid = urllib.parse.quote(user_id, safe="")
    r = _pgrest("PATCH", f"garmin_connections?user_id=eq.{uid}", json={"last_sync_at": _now()})
    r.raise_for_status()


def disconnect(user_id: str) -> None:
    uid = urllib.parse.quote(user_id, safe="")
    r = _pgrest("PATCH", f"garmin_connections?user_id=eq.{uid}", json={"status": "disconnected"})
    r.raise_for_status()


def get_client_for_user(user_id: str) -> Garmin:
    """Restore a Garmin client from the user's stored, encrypted token.

    garminconnect 0.3.x's login(tokenstore=...) accepts the raw dumped token
    string directly - anything over 512 chars is treated as inline token
    data rather than a file path (see garminconnect/__init__.py) - so no temp
    files are needed to restore a session, per-user or otherwise.
    """
    row = get_connection(user_id)
    if not row or row.get("status") != "connected":
        raise NeedsReauth()
    token = decrypt_token(row["encrypted_token"])
    client = Garmin()
    try:
        client.login(tokenstore=token)
    except GarminConnectAuthenticationError:
        # The stored token itself is genuinely dead (revoked, or Garmin no
        # longer accepts it) - garminconnect already tried its own recovery
        # (proactive DI-token refresh, discarding a poisoned cache) before
        # raising this, and can't go further without a password, which we
        # never store. This is the only case that actually needs the user to
        # reconnect.
        mark_needs_reauth(user_id)
        raise NeedsReauth() from None
    # Anything else (GarminConnectConnectionError, GarminConnectTooManyRequestsError,
    # a network blip, a transient anti-bot challenge) leaves the connection's
    # stored status alone - the token is likely still fine, so the next request
    # just retries instead of forcing the user through a manual reconnect for
    # something that wasn't their doing and wasn't really a disconnect.
    return client
