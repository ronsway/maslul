"""
Garmin connection token generator (for accounts with MFA)
===========================================================
Maslul connects most Garmin accounts straight from the app (Settings > Garmin
> email+password). The one case that can't be done from the app is an account
with MFA/2FA enabled: the login library's MFA challenge only works within a
single continuous process blocking on input() for the code, which a
stateless web request can't do (see CLAUDE.md's "Garmin auth" section). This
script runs that continuous login locally, then hands you a token to paste
into Maslul's "יש לי כבר טוקן" field instead.

Runs anywhere with Python, including Google Colab from a phone browser
(colab.research.google.com -> New notebook -> paste -> run):

    pip install garminconnect
    python generate_token.py

By default, prompts for Garmin email and password (and an MFA code if Garmin
asks for one). To skip the prompts on repeat runs, create scripts/.env.garmin
(gitignored - covered by the repo's blanket ".env*" rule) with:

    GARMIN_EMAIL=you@example.com
    GARMIN_PASSWORD=your-password

MFA, if triggered, is still asked interactively - there's no way to script a
one-time code. When run locally (not Colab), the token is also written to
server/.env.garth_token (gitignored, never printed in full) purely as a local
backup copy - the token itself is meant to be pasted into the app, not pushed
anywhere with the Vercel CLI anymore.
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
    print(f"\nToken saved locally to {token_file} (backup copy).")
except OSError:
    pass  # e.g. running in Colab where server/ doesn't exist - fine, just print below

print("\n\n===== paste the line below into Maslul > Settings > Garmin > "
      "\"יש לי כבר טוקן\" =====\n")
print(token)
print("\n===== end =====")
