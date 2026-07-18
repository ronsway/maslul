"""
One-time Garmin token generator
================================
Run this ONCE to produce the GARTH_TOKEN string for the backend.
Runs anywhere with Python, including Google Colab from a phone browser
(colab.research.google.com -> New notebook -> paste -> run).

    pip install garminconnect
    python generate_token.py

Enter your Garmin email and password when prompted. If MFA is on, you will
also be asked for a code. Copy the long string printed after GARTH_TOKEN=
and paste it into the backend env vars (Vercel: Settings -> Environment
Variables -> GARTH_TOKEN). Do NOT paste it into a chat. It is valid ~1 year.
"""

from getpass import getpass
from garminconnect import Garmin

email = input("Garmin email: ").strip()
password = getpass("Garmin password: ")   # hidden in a terminal; visible in Colab (that is fine)

client = Garmin(email, password, prompt_mfa=lambda: input("MFA code (if asked): "))
client.login()

print("\n\n===== copy the line below into GARTH_TOKEN =====\n")
print(client.garth.dumps())
print("\n===== end =====")
