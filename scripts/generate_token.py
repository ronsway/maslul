"""
One-time Garmin token generator
================================
Run this ONCE to produce the GARTH_TOKEN string for the backend.
Runs anywhere with Python, including Google Colab from a phone browser
(colab.research.google.com -> New notebook -> paste -> run).

    pip install garminconnect
    python generate_token.py

Enter your Garmin email and password when prompted. If MFA is on, you will
also be asked for a code. When run locally (not Colab), the token is written
straight to server/.env.garth_token (gitignored, never printed in full) so
scripts/set_garth_token.bat can push it to Vercel without it ever passing
through a chat or being retyped by hand.
"""

from getpass import getpass
from pathlib import Path

from garminconnect import Garmin

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
