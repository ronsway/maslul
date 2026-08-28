"""
One-time Garmin token generator
================================
Run this to produce the GARTH_TOKEN string for the backend, e.g. whenever the
stored token gets rejected (401 / "Failed to retrieve social profile") and
needs replacing. Runs anywhere with Python, including Google Colab from a
phone browser (colab.research.google.com -> New notebook -> paste -> run).

    pip install garminconnect
    python generate_token.py

By default, prompts for Garmin email and password (and an MFA code if Garmin
asks for one). To skip the prompts on repeat runs, create scripts/.env.garmin
(gitignored - covered by the repo's blanket ".env*" rule) with:

    GARMIN_EMAIL=you@example.com
    GARMIN_PASSWORD=your-password

MFA, if triggered, is still asked interactively - there's no way to script a
one-time code. When run locally (not Colab), the token is written straight to
server/.env.garth_token (gitignored, never printed in full) so
scripts/set_garth_token.bat can push it to Vercel without it ever passing
through a chat or being retyped by hand.
"""

from getpass import getpass
from pathlib import Path

from garminconnect import Garmin

def _load_dotenv_creds():
    """Minimal KEY=VALUE reader for scripts/.env.garmin - no extra dependency."""
    env_file = Path(__file__).resolve().parent / ".env.garmin"
    if not env_file.exists():
        return None, None
    values = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values.get("GARMIN_EMAIL"), values.get("GARMIN_PASSWORD")

email, password = _load_dotenv_creds()
if email and password:
    print(f"Using saved credentials from scripts/.env.garmin ({email})")
else:
    email = input("Garmin email: ").strip()
    password = getpass("Garmin password: ")   # hidden in a terminal; visible in Colab (that is fine)

client = Garmin(email, password, prompt_mfa=lambda: input("MFA code (if asked): "))
client.login()

# garminconnect 0.3.x exposes the garth session as client.client
token = client.client.dumps()

token_file = Path(__file__).resolve().parent.parent / "server" / ".env.garth_token"
try:
    with open(token_file, "w", newline="") as f:
        f.write(token)
    print(f"\nToken written to {token_file}")
    print("Run scripts\\set_garth_token.bat to push it to Vercel.")
except OSError:
    # e.g. running in Colab where server/ doesn't exist - fall back to printing
    print("\n\n===== copy the line below into GARTH_TOKEN =====\n")
    print(token)
    print("\n===== end =====")
