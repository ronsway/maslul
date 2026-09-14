# Maslul (מסלול)

A personal running training planner that pushes structured workouts to a
Garmin watch.

Each user connects their own Garmin account and gets their own plan, synced
to the cloud (Supabase). Not a public product - for the owner and a few
trusted people.

## Structure
- `web/index.html` - the app (PWA, Hebrew RTL, single file, no build step).
  Includes `manifest.json`, `sw.js`, icons, and app-store screenshots.
- `server/` - the backend (FastAPI on Vercel) that translates and schedules
  workouts on Garmin, and manages each user's private Garmin connection
  (`server/api/garmin_auth.py`).
- `scripts/generate_token.py` - generates a Garmin token locally (for the MFA
  case the in-app connect flow can't handle).
- `scripts/capture_screenshots.py` - app-store screenshots (Playwright, one-off).
- `deploy.bat` - the normal deploy workflow: bumps the version, deploys
  backend+frontend to Vercel, then commits+pushes. See `CHANGELOG.md` for
  deploy history.
- `CLAUDE.md` - full project context: the workout data model, per-user Garmin
  auth, Android APK packaging, UI conventions, and more.

## Quick start
1. Deploy `server/` to Vercel (root directory: `server/`), add the env vars
   `GARMIN_TOKEN_ENCRYPTION_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_ROLE_KEY` (details in `CLAUDE.md`).
2. Run `server/sql/garmin_connections.sql` once in the Supabase SQL editor.
3. Publish `web/` (GitHub Pages or Vercel static).
4. Each user signs in with Google/email and connects their own Garmin account
   from Settings > Garmin in the app - no single global token to configure.

For later deploys, just run `deploy.bat` from the repo root. Full details in
`CLAUDE.md`.

## License

All rights reserved - see [LICENSE](LICENSE).
