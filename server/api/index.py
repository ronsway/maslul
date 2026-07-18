"""
Maslul - Garmin backend (Vercel serverless, ASGI)
=================================================
Receives a week of workouts from the PWA, translates each into a structured
Garmin running workout (warmup / repeat groups of effort+recovery / cooldown),
uploads and schedules them to the given dates.

Auth: uses a long-lived Garth token from the GARTH_TOKEN env var. No password
is ever sent per request. Generate the token once with scripts/generate_token.py
(runs fine in Google Colab from a phone) and paste it into the Vercel env vars.

Optional: set API_SECRET in the Vercel env to require an x-api-secret header,
so the public endpoint is not open to anyone.

Vercel picks up the module-level `app` (ASGI). See vercel.json for routing.
Local run (optional): uvicorn api.index:app --reload --port 8000
"""

import os
from typing import List, Optional, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from garminconnect import Garmin
from garminconnect.workout import (
    RunningWorkout, WorkoutSegment,
    create_warmup_step, create_cooldown_step,
    create_interval_step, create_recovery_step,
    create_distance_interval_step, create_repeat_group,
)

app = FastAPI(title="Maslul Garmin Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ---------- request model (matches buildPayload in web/index.html) ----------

class Seg(BaseModel):
    mode: Literal["time", "dist"]
    value: int                       # seconds if time, meters if dist

class Block(BaseModel):
    kind: Literal["repeat", "steady"]
    reps: Optional[int] = None
    work: Optional[Seg] = None
    recovery: Optional[Seg] = None
    mode: Optional[str] = None
    value: Optional[int] = None

class Workout(BaseModel):
    date: str                        # "YYYY-MM-DD"
    name: str
    type: str
    sport: str = "running"
    warmupSec: int = 0
    cooldownSec: int = 0
    blocks: List[Block] = []

class WeekPayload(BaseModel):
    athlete: Optional[dict] = None
    workouts: List[Workout] = []

# ---------- Garmin auth via stored token ----------

def get_client() -> Garmin:
    token = os.environ.get("GARTH_TOKEN")
    if not token:
        raise HTTPException(500, "GARTH_TOKEN env var is not set on the server")
    client = Garmin()
    # loads() restores the saved OAuth1/OAuth2 tokens; auto-refresh handles the rest.
    # NOTE: verify this call against the installed garminconnect version if it errors
    #       (older versions may expose it as client.garth.loads or need Garmin("","")).
    client.garth.loads(token)
    return client

def check_secret(x_api_secret: Optional[str]):
    expected = os.environ.get("API_SECRET")
    if expected and x_api_secret != expected:
        raise HTTPException(401, "bad or missing x-api-secret")

# ---------- workout translation ----------

def make_effort(seg: Seg, recovery: bool):
    if recovery:
        return create_recovery_step(float(seg.value))
    if seg.mode == "dist":
        return create_distance_interval_step(float(seg.value))
    return create_interval_step(float(seg.value))

def build_steps(w: Workout):
    steps = []
    if w.warmupSec:
        steps.append(create_warmup_step(float(w.warmupSec)))
    for b in w.blocks:
        if b.kind == "steady" and b.value:
            if b.mode == "dist":
                steps.append(create_distance_interval_step(float(b.value)))
            else:
                steps.append(create_interval_step(float(b.value)))
        elif b.kind == "repeat" and b.reps and b.work and b.recovery:
            children = [make_effort(b.work, False), make_effort(b.recovery, True)]
            steps.append(create_repeat_group(b.reps, children))
    if w.cooldownSec:
        steps.append(create_cooldown_step(float(w.cooldownSec)))
    return steps

def build_workout(w: Workout) -> RunningWorkout:
    return RunningWorkout(
        workoutName=w.name,
        workoutSegments=[WorkoutSegment(
            segmentOrder=1,
            sportType={"sportTypeId": 1, "sportTypeKey": "running"},
            workoutSteps=build_steps(w),
        )],
    )

# ---------- routes ----------

@app.get("/")
def health():
    return {"status": "ok", "service": "maslul-garmin", "token_set": bool(os.environ.get("GARTH_TOKEN"))}

@app.post("/schedule-week")
def schedule_week(payload: WeekPayload, x_api_secret: Optional[str] = Header(default=None)):
    check_secret(x_api_secret)
    try:
        client = get_client()
    except HTTPException:
        raise
    except Exception as e:
        return {"results": [], "error": f"garmin auth failed: {e}"}

    results = []
    for w in payload.workouts:
        try:
            wk = build_workout(w)
            res = client.upload_running_workout(wk)
            wid = res.get("workoutId") if isinstance(res, dict) else res
            client.schedule_workout(wid, w.date)
            results.append({"name": w.name, "date": w.date, "ok": True, "workoutId": wid})
        except Exception as e:
            results.append({"name": w.name, "date": w.date, "ok": False, "error": str(e)})
    return {"results": results}
