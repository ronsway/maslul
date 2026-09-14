# Maslul (מסלול) - running training planner for Garmin

A personal PWA that builds structured running workouts and pushes them to the
owner's Garmin watch. Weekly view, swipe between weeks, one or more workouts per
day, each with warmup + main set + cooldown. Once a week the owner sends the week
to Garmin Connect; the workouts then sync to the watch as scheduled daily workouts.

Built for one owner, but usable by a few trusted people who sign in with
Google (Supabase auth) - each connects their own Garmin account (see "Garmin
auth" below) and gets their own plan, synced per account. Not a public
product. Hebrew UI, right to left.

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
2. Auth is per user, TOKEN based, not password per request - see "Garmin auth
   (per user)" below for the full model (replaced the single global
   `GARTH_TOKEN` env var in 2026-08).
3. As of 2026-08, `scripts/generate_token.py` had hit a Garmin login page titled
   "GARMIN Authentication Application" (the real title Garmin's authenticator-app
   MFA challenge uses) even though the owner reported not using MFA on that
   account — likely explanation found later the same month while building
   per-user connect (see "Garmin auth" below): `garminconnect`'s widget-flow
   login strategy can land on that page as an anti-bot/rate-limit challenge
   even for accounts without MFA truly enabled, not only for real MFA.
   `garminconnect` is pinned to `0.3.9` regardless, since its `mobile`/`portal`
   login strategies handle rate limits and MFA more robustly than `0.3.6`'s
   `widget` fallback.
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

## Garmin auth (per user)

Each user connects their own Garmin account; there is no more single global
identity. Every backend route that touches Garmin requires an
`Authorization: Bearer <supabase access token>` header (the frontend already
has this from Supabase auth) - `server/api/garmin_auth.py`'s `verify_user()`
validates it by asking Supabase's own `/auth/v1/user` endpoint (works
regardless of the project's JWT signing scheme, no secret to manage locally)
and returns the caller's Supabase user id.

That id is the primary key into a `garmin_connections` table in the same
Supabase Postgres project already used for `user_data` (schema:
`server/sql/garmin_connections.sql`, applied by hand in the Supabase SQL
editor - this repo has no migration tooling). Each row holds one user's
Garmin token, AES-256-GCM encrypted (key: `GARMIN_TOKEN_ENCRYPTION_KEY`) and
accessed only by the backend via Supabase's PostgREST API with the
service-role key - the frontend never queries this table directly, unlike
`user_data`.

Connecting an account, from the app (`web/index.html`, Settings > Garmin,
`garminSectionHTML()`/`connectGarmin()`):
- `POST /garmin/connect` with email+password. Works for accounts without MFA.
- If Garmin challenges for MFA, this returns `{"status":"mfa_required"}`
  instead of hanging: garminconnect 0.3.9's MFA state (`_mfa_session` and
  friends) lives only on one in-memory Python object with no way to export
  and resume it, so a "submit password now, code later" flow across two
  separate Vercel requests isn't something the library supports. The app
  falls back to `POST /garmin/connect-token`: paste a token generated by
  running `scripts/generate_token.py` locally (same script that used to
  produce `GARTH_TOKEN` - it still handles MFA fine because it's one
  continuous local process that can block on `input()` for the code).

`GET /garmin/status` / `DELETE /garmin/connection` read/clear the caller's
own row. `get_client_for_user()` restores a session straight from the stored
token string - `garminconnect`'s `Garmin().login(tokenstore=...)` accepts the
raw dumped token directly once it's over 512 chars (treated as inline data,
not a file path), so no temp files are needed, per-user or otherwise.

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

- `GARMIN_TOKEN_ENCRYPTION_KEY` (required) - base64 32-byte AES-256-GCM key
  encrypting Garmin tokens at rest. Generate once:
  `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.
- `SUPABASE_URL` (required) - same project the frontend uses
  (`https://qvbdnaeewytfoolmubch.supabase.co`, already hardcoded as a
  fallback default in `garmin_auth.py`, but set explicitly anyway).
- `SUPABASE_ANON_KEY` (required) - same publishable key hardcoded in
  `web/index.html`; used to validate a caller's session token against
  Supabase's `/auth/v1/user`.
- `SUPABASE_SERVICE_ROLE_KEY` (required) - Supabase dashboard > Settings >
  API. Bypasses RLS for the backend's `garmin_connections` reads/writes.
  Never expose this to the frontend.

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
2. Set root directory to `server/`. Add the four env vars from "Environment
   variables" above.
3. Apply `server/sql/garmin_connections.sql` once in the Supabase SQL editor
   (not part of `deploy.bat` - no migration tooling in this repo).
4. Deploy. Health check: `GET https://<project>.vercel.app/` returns
   `{"status":"ok"}`.
5. Each user connects their own Garmin account from Settings > Garmin in the
   app (see "Garmin auth" above) - nothing to configure per-deploy anymore.
   `BACKEND_BASE`/`BACKEND_URL` in `web/index.html` are still hardcoded
   constants, not user-configurable.

Frontend: publish `web/index.html` to GitHub Pages (repo owner: `ronsway`) or any
static host. CORS on the backend is open, so any origin works.

Verify Vercel routing on first deploy. If `/schedule-week` 404s, the FastAPI app is
still reachable at `/api/index`; adjust `server/vercel.json` rewrites or the app's
backend URL accordingly.

## Android packaging (APK)

The PWA (already a proper installable app - `web/manifest.json` +
`web/sw.js`) gets wrapped into a sideloadable Android APK via
[PWABuilder](https://www.pwabuilder.com) (Google's Bubblewrap TWA builder
under the hood) rather than a native rebuild - no Capacitor/Cordova, no
separate codebase, since the project is deliberately zero-build vanilla JS.

Flow: PWABuilder > enter `https://maslul-web.vercel.app` > Package For Stores
> Android > Google Play > "Generate Package" with signing key "New". Downloads
a zip containing `Maslul.apk` (sideload this), `Maslul.aab` (Play Store only,
unused), `signing.keystore` + `signing-key-info.txt` (**keep these safe** -
required for any future update of the same install, not just a replacement
app), and `assetlinks.json`.

That `assetlinks.json` is committed at `web/.well-known/assetlinks.json` -
proves to Android that the TWA package (`app.vercel.maslul_web.twa`, declared
in `manifest.json`'s `related_applications`) and this origin share the same
owner, via the signing key's SHA-256 fingerprint. Without it the installed
APK shows a Chrome address bar; with it, full standalone.

Manifest fields added specifically for PWABuilder/Android (beyond the
original PWA basics): `id`, `orientation`, `categories`,
`prefer_related_applications`, `related_applications`, `launch_handler`
(`focus-existing`), `display_override`, and `screenshots` (real app
screenshots with seeded demo data, captured via the one-off
`scripts/capture_screenshots.py` Playwright script - rerun by hand if the UI
changes enough to need updated ones, not part of `deploy.bat`).
`shortcuts` (long-press the installed icon for "add workout" / "send week")
are wired to real behavior, not placeholders: they land as
`?shortcut=add|send` on first load, handled once in `onAuthStateChange` by
`runLaunchShortcut()` after cloud data loads, then stripped from the URL.

Deliberately left alone (score independently as PWABuilder's "optional/
enhancement" tier, don't fake them just to move the number): `file_handlers`,
`protocol_handlers`, `share_target`, `widgets`, `edge_side_panel`,
`note_taking`, `scope_extensions` (none apply to a single-purpose,
single-origin running planner), and `iarc_rating_id` (only exists after a
Play Store content-rating submission - not applicable to sideloading).

Rebuilding the APK after a frontend change: just redo the PWABuilder flow
above - no separate Android project to keep in sync, the manifest/assets are
already right.

## UI conventions

- Popup/sheet trailing action buttons go in one flex row (`display:flex;
  gap:8px`, each button `flex:1; margin:0`), never stacked vertically -
  applies to every sheet, not just the obvious ones (see the `.sheet`/
  `.drawer` templates in `web/index.html` for the pattern). Ghost/cancel-style
  buttons come first in markup, the primary/confirm action last - matches the
  existing delete-workout and duplicate-week confirm dialogs.
- Action buttons packed into a row are text-only, no icons - with 2-3 buttons
  sharing a row, an icon just eats space without adding clarity (removed from
  add-workout/auto-generate/duplicate-week/send-day/send-week in v1.0.107
  after first adding them in v1.0.106).
- A short/variable-height sheet needs `.sheet.compact` (rounds all 4 corners)
  or `.sheet.tall` (rounds all 4 with a deliberate bottom gap even when
  maxed out) - the base `.sheet` class only rounds the top corners, meant for
  content that reaches the viewport bottom. Forgetting the modifier shows a
  flat, cut-off-looking bottom edge against the scrim.
- No debug/dev-facing UI in the app itself (e.g. a "show JSON payload" button
  was removed in v1.0.111 - no value to the end user, use the browser's
  network tab or a local script instead if payload inspection is ever needed
  again).

## Roadmap (in order)

1. DONE - backend deployed to Vercel.
2. DONE - Supabase (Google) auth, plan/profile synced per cloud account (since v1.0.6).
3. DONE - non-running types: rowing, elliptical, strength (v1.0.50), yoga and
   crossfit (v1.0.55+). See "Key decisions" #4 for the sport/kind model.
4. DONE - per-user Garmin connections (2026-08), replacing the single global
   `GARTH_TOKEN`. See "Garmin auth (per user)".
5. DONE - duplicate last week (v1.0.96): `confirmDupWeek()`/`applyDupWeek()` in
   `web/index.html`, copies `S.plan` day-for-day from `weekDates(offset-1)` onto
   the current week, skipping race-linked workouts and resetting
   `garminWorkoutId`/`done`/`actual` on the copies.
6. DONE - Android packaging (v1.0.96-v1.0.110). See "Android packaging (APK)"
   below.
7. Nice-to-haves (next up): workout templates/library, target pace/HR zones from
   the profile, editing an already-pushed week (delete + re-upload).

## Owner working preferences

- Hebrew for UI and personal-facing text; English is fine for code and
  technical docs - `README.md` specifically should be English (was Hebrew
  until 2026-09, corrected on request).
- Repo is private on GitHub; the app has an explicit proprietary "all rights
  reserved" `LICENSE` (added 2026-09, not MIT/GPL - deliberate choice, don't
  swap it without asking).
- Terse and directive. Wants proactive execution and expert guidance, not meandering.
- Clean formatting, no em dashes, no decorative check marks.
- GitHub username: `ronsway`, comfortable with GitHub Pages.
