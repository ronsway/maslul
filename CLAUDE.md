# Maslul (מסלול) - running training planner for Garmin

A personal PWA that builds structured running workouts and pushes them to the
owner's Garmin watch. Weekly view, swipe between weeks, one or more workouts per
day, each with warmup + main set + cooldown. Once a week the owner sends the week
to Garmin Connect; the workouts then sync to the watch as scheduled daily workouts.

Single user, personal use. Hebrew UI, right to left.

## Architecture

Two decoupled parts, one repo:

- `web/index.html` - the PWA. Single self-contained file, vanilla JS, no build step.
  Hebrew RTL. State persists in localStorage (falls back to in-memory in sandboxed
  previews). Talks to the backend over one POST to `/schedule-week`.
- `server/` - FastAPI backend deployed as a Vercel Python function. Translates the
  app's workout JSON into a structured Garmin `RunningWorkout` and schedules it.
  Uses the unofficial `garminconnect` library (Garmin has no public consumer API).

Frontend and backend can be deployed separately. Frontend can go to GitHub Pages
(owner already uses it) or Vercel static; backend goes to Vercel Python.

## Key decisions (already made, do not re-litigate without asking)

1. Garmin integration uses the UNofficial `garminconnect` library, not the official
   Garmin Connect Developer Program Training API. The official API needs Garmin
   business approval and is slow; the unofficial path works now for one user.
2. Auth is TOKEN based, not password per request. A long-lived Garth token
   (~1 year, auto-refresh) lives in the `GARTH_TOKEN` env var. Password is never
   sent from the app or stored. Token generated once via `scripts/generate_token.py`.
3. As of 2026-08, `scripts/generate_token.py` has hit a Garmin login page titled
   "GARMIN Authentication Application" (the real title Garmin's authenticator-app
   MFA challenge uses) even though the owner reports not using MFA — cause
   unconfirmed; could be MFA enabled server-side after a security event, or an
   anti-bot challenge reusing that page for a rate-limited IP. `garminconnect` is
   pinned to `0.3.9` regardless, since its `mobile`/`portal` login strategies
   handle rate limits and MFA more robustly than `0.3.6`'s `widget` fallback.
4. First version is RUNNING ONLY. Strength / rowing / elliptical come later
   (Garmin restricts third-party strength pushes; those will use
   `FitnessEquipmentWorkout` and may land with reduced structure).

## Known fragility (important)

Garmin keeps changing its auth flow. `matin/garth` is marked deprecated, but the
maintained `cyberjunky/python-garminconnect` (updated 2026) works around it by
trying multiple login strategies. Expect occasional breakage on login and be ready
to pin or bump the `garminconnect` version. The step-builder helper signatures
(`create_interval_step`, `create_repeat_group`, etc.) may differ across versions.
If a call errors, check the installed version:
`python -c "import garminconnect.workout as w; help(w)"`.

## Workout data model (frontend -> backend JSON)

```json
{
  "athlete": { "name": "...", "maxHR": "...", "restHR": "..." },
  "workouts": [{
    "date": "2027-05-04",
    "name": "אינטרוולים",
    "type": "intervals|hills|fartlek|volume",
    "sport": "running",
    "warmupSec": 600,
    "cooldownSec": 600,
    "blocks": [
      { "kind": "repeat", "reps": 6,
        "work":     { "mode": "time|dist", "value": 180 },
        "recovery": { "mode": "time|dist", "value": 120 } },
      { "kind": "steady", "mode": "time|dist", "value": 2700 }
    ]
  }]
}
```
`mode: time` -> value in seconds. `mode: dist` -> value in meters.
Backend maps: warmup -> `create_warmup_step`, repeat block ->
`create_repeat_group(reps, [effort, recovery])`, steady -> interval/distance step,
cooldown -> `create_cooldown_step`.

## Environment variables (backend, set in Vercel)

- `GARTH_TOKEN` (required) - the Garmin token string from generate_token.py
- `API_SECRET` (optional) - if set, requests must send header `x-api-secret`.
  The app has a matching "קוד סודי" field under the send sheet.

## Deploy

Backend (Vercel, from the `server/` folder as project root):
1. Push repo to GitHub, or use the Vercel CLI / dashboard.
2. Set root directory to `server/`. Add `GARTH_TOKEN` (and optionally `API_SECRET`).
3. Deploy. Health check: `GET https://<project>.vercel.app/` returns
   `{"status":"ok","token_set":true}`.
4. In the app, open the profile/send sheet and set the backend URL to
   `https://<project>.vercel.app/schedule-week` and the secret if used.

Frontend: publish `web/index.html` to GitHub Pages (repo owner: `ronsway`) or any
static host. CORS on the backend is open, so any origin works.

Verify Vercel routing on first deploy. If `/schedule-week` 404s, the FastAPI app is
still reachable at `/api/index`; adjust `server/vercel.json` rewrites or the app's
backend URL accordingly.

## Roadmap (in order)

1. Deploy backend to Vercel, wire GARTH_TOKEN, confirm a real workout reaches the watch.
2. Supabase auth so the plan is tied to a cloud user account, not just one device.
   Owner already uses Supabase; store workouts and the plan per user.
3. Add non-running types: strength, rowing, elliptical (FitnessEquipmentWorkout /
   strength workout models), accepting reduced structure where Garmin limits it.
4. Nice-to-haves: workout templates/library, target pace/HR zones from the profile,
   duplicating a week, editing an already-pushed week (delete + re-upload).

## Owner working preferences

- Hebrew for UI and personal-facing text; English is fine for code and technical docs.
- Terse and directive. Wants proactive execution and expert guidance, not meandering.
- Clean formatting, no em dashes, no decorative check marks.
- GitHub username: `ronsway`, comfortable with GitHub Pages.
