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
   To refresh it (e.g. after a Garmin-side 401/"Failed to retrieve social
   profile" error), run `scripts/refresh_token.bat` - prompts for Garmin
   credentials once, writes the token, then pushes it to Vercel and redeploys
   the backend in one go (chains `generate_token.py` + `set_garth_token.bat`).
3. As of 2026-08, `scripts/generate_token.py` has hit a Garmin login page titled
   "GARMIN Authentication Application" (the real title Garmin's authenticator-app
   MFA challenge uses) even though the owner reports not using MFA — cause
   unconfirmed; could be MFA enabled server-side after a security event, or an
   anti-bot challenge reusing that page for a rate-limited IP. `garminconnect` is
   pinned to `0.3.9` regardless, since its `mobile`/`portal` login strategies
   handle rate limits and MFA more robustly than `0.3.6`'s `widget` fallback.
4. As of 2026-08, six sports are supported: running, rowing, elliptical,
   strength, crossfit, yoga. Sport is the top-level pick in the UI; running/
   rowing/elliptical additionally take a "kind" sub-type (intervals, tempo,
   hills, fartlek, volume, recovery - plus race, running-only). Strength/
   crossfit have no kind - they're sets-of-reps (`exercises`, not `blocks`)
   with no dedicated Garmin workout model, so the backend builds them as
   `BaseWorkout` tagged `strength_training`/`hiit`. Yoga is also `BaseWorkout`
   (tagged `yoga` - Garmin has the sport type but no dedicated model class).
   Crossfit's exercise list is meant to be system-generated, not hand-built:
   `generateCrossfitExercises()` picks a random 5-6 movements from a curated
   pool with randomized sets/reps/rest; the editor shows the result as a
   read-only summary by default (manual per-exercise editing is one tap away
   behind "ערוך ידנית", not the default view).
5. Sport-picker icons are pictograms cropped directly out of an AI-generated
   reference image the owner supplied (not hand-drawn), background stripped
   and recolored per sport's accent color, embedded as base64 PNG data URIs
   in `SPORT_ICON_DATA` (`web/index.html`) - keeps the file self-contained
   with no separate asset folder. If icons need to change again, redo the
   crop-and-recolor from a reference image rather than hand-drawing SVG paths
   - attempts at that were repeatedly rejected as looking incomplete/wrong.

## Known fragility (important)

Garmin keeps changing its auth flow. `matin/garth` is marked deprecated, but the
maintained `cyberjunky/python-garminconnect` (updated 2026) works around it by
trying multiple login strategies. Expect occasional breakage on login and be ready
to pin or bump the `garminconnect` version. The step-builder helper signatures
(`create_interval_step`, `create_repeat_group`, etc.) may differ across versions.
If a call errors, check the installed version:
`python -c "import garminconnect.workout as w; help(w)"`.

## Workout data model (frontend -> backend JSON)

`sport` (running|rowing|elliptical|strength|crossfit|yoga) drives the backend's
Garmin sport-type dispatch and step-builder choice. `type` is the sub-"kind"
for cardio sports (intervals|tempo|hills|fartlek|volume|recovery|race, race
running-only) - for strength/crossfit/yoga, `type` just equals `sport` (no
sub-kind). Cardio sports use `blocks`; strength/crossfit use `exercises`
instead (sets-of-reps has no time/dist shape) and `blocks` stays `[]`; yoga
uses a single `blocks` steady entry like any other cardio sport.

```json
{
  "athlete": { "name": "...", "maxHR": "...", "restHR": "..." },
  "workouts": [{
    "date": "2027-05-04",
    "name": "אינטרוולים",
    "type": "intervals",
    "sport": "running",
    "warmupSec": 600,
    "cooldownSec": 600,
    "blocks": [
      { "kind": "repeat", "reps": 6,
        "work":     { "mode": "time|dist", "value": 180 },
        "recovery": { "mode": "time|dist", "value": 120 } },
      { "kind": "steady", "mode": "time|dist", "value": 2700 }
    ],
    "exercises": []
  }]
}
```
`mode: time` -> value in seconds. `mode: dist` -> value in meters. A strength/
crossfit workout instead carries `"exercises": [{ "category": "SQUAT", "sets": 3,
"reps": 10, "weightKg": null, "restSec": 90 }, ...]` (`category` is a Garmin
exercise-category key, see `STRENGTH_CATEGORIES`/`CROSSFIT_CATEGORIES` in
`web/index.html`) and `blocks: []`.

Backend maps: warmup -> `create_warmup_step`, repeat block ->
`create_repeat_group(reps, [effort, recovery])`, steady -> interval/distance step,
cooldown -> `create_cooldown_step`. `exercises` -> `build_strength_steps`
(warmup + one `create_strength_set` per exercise + cooldown), used for both
strength and crossfit.

## Environment variables (backend, set in Vercel)

- `GARTH_TOKEN` (required) - the Garmin token string from generate_token.py
- `API_SECRET` (optional) - if set, requests must send header `x-api-secret`.
  The app has a matching "קוד סודי" field under the send sheet.

## Deploy

Normal workflow: run `deploy.bat` from the repo root (optionally with a message,
e.g. `deploy.bat fix send button`). It bumps `VERSION` (patch), regenerates
`web/version.js` and `web/sw.js`'s cache name via `scripts/bump_version.js` (so
installed PWAs actually pick up the new build instead of serving a stale cached
one), deploys `server/` and `web/` to Vercel production, then commits and pushes
the version bump. The current version is shown at the bottom of the in-app
Settings drawer - useful for confirming a device is actually running the latest
build rather than a stale cached PWA. See `CHANGELOG.md` for the deploy history.

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

1. DONE - backend deployed to Vercel, GARTH_TOKEN wired.
2. DONE - Supabase (Google) auth, plan/profile synced per cloud account (since v1.0.6).
3. DONE - non-running types: rowing, elliptical, strength (v1.0.50), yoga and
   crossfit (v1.0.55+). See "Key decisions" #4 for the sport/kind model.
4. Nice-to-haves (next up): workout templates/library, target pace/HR zones from
   the profile, duplicating a week, editing an already-pushed week (delete +
   re-upload).

## Owner working preferences

- Hebrew for UI and personal-facing text; English is fine for code and technical docs.
- Terse and directive. Wants proactive execution and expert guidance, not meandering.
- Clean formatting, no em dashes, no decorative check marks.
- GitHub username: `ronsway`, comfortable with GitHub Pages.
