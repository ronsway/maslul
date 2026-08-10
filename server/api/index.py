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
    RunningWorkout, WorkoutSegment, ExecutableStep,
    ConditionType, StepType, TargetType,
    create_warmup_step, create_cooldown_step,
    create_interval_step, create_recovery_step, create_repeat_group,
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
    pace: Optional[float] = None     # seconds per km target, steady+dist blocks only (e.g. race splits)

class Workout(BaseModel):
    date: str                        # "YYYY-MM-DD"
    name: str
    type: str
    sport: str = "running"
    warmupSec: int = 0
    cooldownSec: int = 0
    blocks: List[Block] = []
    garminWorkoutId: Optional[int] = None   # id from a previous send, so it can be replaced instead of duplicated

class WeekPayload(BaseModel):
    athlete: Optional[dict] = None
    workouts: List[Workout] = []

# ---------- Garmin auth via stored token ----------

def _describe_exception(e: Exception, depth: int = 4) -> str:
    """garminconnect wraps failures (e.g. 'Failed to retrieve social profile')
    without including the underlying cause in the message, and only logs it at
    debug level - which Vercel doesn't capture. Walk __cause__/__context__ so
    the actual root error (HTTP status, timeout, etc.) reaches the response.
    """
    parts = [str(e)]
    cur = e
    for _ in range(depth):
        nxt = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
        if not nxt or nxt is cur:
            break
        parts.append(f"{type(nxt).__name__}: {nxt}")
        cur = nxt
    return " | caused by: ".join(parts)

def get_client() -> Garmin:
    token = os.environ.get("GARTH_TOKEN")
    if not token:
        raise HTTPException(500, "GARTH_TOKEN env var is not set on the server")
    client = Garmin()
    # garminconnect 0.3.x: login(tokenstore=...) accepts the raw token string
    # (>512 chars) produced by client.client.dumps() in scripts/generate_token.py.
    # It restores the OAuth tokens and refreshes them if they are about to expire.
    client.login(tokenstore=token)
    return client

def check_secret(x_api_secret: Optional[str]):
    expected = os.environ.get("API_SECRET")
    if expected and x_api_secret != expected:
        raise HTTPException(401, "bad or missing x-api-secret")

# ---------- workout translation ----------

# garminconnect 0.3.x has no distance-step helper; build the step directly.
# step_type: StepType value + its key/displayOrder as Garmin Connect expects.
_STEP_TYPES = {
    "interval": {"stepTypeId": StepType.INTERVAL, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": StepType.RECOVERY, "stepTypeKey": "recovery", "displayOrder": 4},
}

def create_distance_step(meters: float, step_order: int, kind: str, pace_sec_per_km: Optional[float] = None) -> ExecutableStep:
    target = {
        "workoutTargetTypeId": TargetType.NO_TARGET,
        "workoutTargetTypeKey": "no.target",
        "displayOrder": 1,
    }
    extra = {}
    if pace_sec_per_km:
        # Garmin pace/speed targets are expressed as a speed range in m/s;
        # +-3% around the goal pace gives a workable band rather than a single point.
        speed = 1000.0 / pace_sec_per_km
        target = {
            "workoutTargetTypeId": TargetType.PACE_ZONE,
            "workoutTargetTypeKey": "pace.zone",
            "displayOrder": 5,
        }
        extra = {"targetValueOne": round(speed * 0.97, 3), "targetValueTwo": round(speed * 1.03, 3)}
    return ExecutableStep(
        stepOrder=step_order,
        stepType=_STEP_TYPES[kind],
        endCondition={
            "conditionTypeId": ConditionType.DISTANCE,
            "conditionTypeKey": "distance",
            "displayOrder": 1,
            "displayable": True,
        },
        endConditionValue=meters,
        targetType=target,
        **extra,
    )

def make_effort(seg: Seg, recovery: bool, order: int):
    kind = "recovery" if recovery else "interval"
    if seg.mode == "dist":
        return create_distance_step(float(seg.value), order, kind)
    if recovery:
        return create_recovery_step(float(seg.value), order)
    return create_interval_step(float(seg.value), order)

def build_steps(w: Workout):
    steps = []
    order = 1
    if w.warmupSec:
        steps.append(create_warmup_step(float(w.warmupSec), order)); order += 1
    for b in w.blocks:
        if b.kind == "steady" and b.value:
            if b.mode == "dist":
                steps.append(create_distance_step(float(b.value), order, "interval", b.pace))
            else:
                steps.append(create_interval_step(float(b.value), order))
            order += 1
        elif b.kind == "repeat" and b.reps and b.work and b.recovery:
            group_order = order
            children = [
                make_effort(b.work, False, order + 1),
                make_effort(b.recovery, True, order + 2),
            ]
            steps.append(create_repeat_group(b.reps, children, group_order))
            order += 3
    if w.cooldownSec:
        steps.append(create_cooldown_step(float(w.cooldownSec), order))
    return steps

# rough seconds-per-meter used only for the required duration estimate
_SEC_PER_METER = 0.36

def _seg_secs(seg: Seg) -> float:
    return seg.value if seg.mode == "time" else seg.value * _SEC_PER_METER

def estimate_secs(w: Workout) -> int:
    total = float(w.warmupSec + w.cooldownSec)
    for b in w.blocks:
        if b.kind == "steady" and b.value:
            total += _seg_secs(Seg(mode=b.mode or "time", value=b.value))
        elif b.kind == "repeat" and b.reps and b.work and b.recovery:
            total += b.reps * (_seg_secs(b.work) + _seg_secs(b.recovery))
    return int(total)

def build_workout(w: Workout) -> RunningWorkout:
    return RunningWorkout(
        workoutName=w.name,
        estimatedDurationInSecs=estimate_secs(w),
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
        return {"results": [], "error": f"garmin auth failed: {_describe_exception(e)}"}

    results = []
    for w in payload.workouts:
        try:
            if w.garminWorkoutId:
                # replace, don't duplicate: remove the previously-sent workout (which also
                # drops its scheduled entry) before uploading the current version.
                try:
                    client.delete_workout(w.garminWorkoutId)
                except Exception:
                    pass  # already gone / never existed - fine, proceed to create fresh
            wk = build_workout(w)
            res = client.upload_running_workout(wk)
            wid = res.get("workoutId") if isinstance(res, dict) else res
            client.schedule_workout(wid, w.date)
            results.append({"name": w.name, "date": w.date, "ok": True, "workoutId": wid})
        except Exception as e:
            results.append({"name": w.name, "date": w.date, "ok": False, "error": str(e)})
    return {"results": results}

@app.get("/activities")
def activities(since: str, until: Optional[str] = None, x_api_secret: Optional[str] = Header(default=None)):
    """Completed runs in a date range, for matching back against pushed workouts.
    `workoutId` on the activity (when present) is the same id returned by
    /schedule-week when the structured workout was uploaded, so the frontend
    can match a completed run to its plan entry exactly instead of guessing
    by date/type.
    """
    check_secret(x_api_secret)
    try:
        client = get_client()
    except HTTPException:
        raise
    except Exception as e:
        return {"activities": [], "error": f"garmin auth failed: {e}"}
    try:
        raw = client.get_activities_by_date(since, until or since, "running")
    except Exception as e:
        return {"activities": [], "error": str(e)}
    out = []
    for a in raw:
        dist_m = a.get("distance") or 0
        dur_s = a.get("duration") or 0
        speed = a.get("averageSpeed") or 0
        out.append({
            "activityId": a.get("activityId"),
            "workoutId": a.get("workoutId"),
            "date": (a.get("startTimeLocal") or "")[:10],
            "name": a.get("activityName"),
            "distanceKm": round(dist_m / 1000, 2),
            "durationSec": round(dur_s),
            "paceSecPerKm": round(1000 / speed) if speed else None,
            "avgHR": a.get("averageHR"),
        })
    return {"activities": out}
