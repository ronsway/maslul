"""
Maslul - Garmin backend (Vercel serverless, ASGI)
=================================================
Receives a week of workouts from the PWA, translates each into a structured
Garmin running workout (warmup / repeat groups of effort+recovery / cooldown),
uploads and schedules them to the given dates.

Auth: per-user. Every route below requires an
`Authorization: Bearer <supabase access token>` header (the same session
token the frontend already gets from Supabase auth); verify_user() checks it
against Supabase and returns the caller's user id, which is the key into the
`garmin_connections` table (encrypted Garmin token per user - see
garmin_auth.py and server/sql/garmin_connections.sql). There is no more
single global Garmin identity - each user connects their own account via
POST /garmin/connect (email+password) or, for accounts with MFA,
POST /garmin/connect-token (paste a token generated locally with
scripts/generate_token.py - see that script and CLAUDE.md for why MFA can't
be completed through this API directly).

Vercel picks up the module-level `app` (ASGI). See vercel.json for routing.
Local run (optional): uvicorn api.index:app --reload --port 8000
"""

from typing import List, Optional, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
from garminconnect.workout import (
    RunningWorkout, FitnessEquipmentWorkout, StrengthWorkout, BaseWorkout,
    WorkoutSegment, ExecutableStep,
    ConditionType, StepType, TargetType,
    create_warmup_step, create_cooldown_step,
    create_interval_step, create_recovery_step, create_repeat_group,
    create_strength_set,
)

try:
    # Vercel's Python runtime loads this file directly (adds its own directory
    # to sys.path), so a flat import resolves the sibling module.
    from garmin_auth import (
        verify_user, get_client_for_user, save_connection, mark_synced,
        disconnect as disconnect_connection, get_connection, NeedsReauth,
    )
except ImportError:
    # Local `uvicorn api.index:app` (documented above) loads this as the
    # api.index submodule of a package instead - needs the relative form.
    from .garmin_auth import (
        verify_user, get_client_for_user, save_connection, mark_synced,
        disconnect as disconnect_connection, get_connection, NeedsReauth,
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

class StrengthExercise(BaseModel):
    category: str                    # Garmin exercise category, e.g. "SQUAT" - see garminconnect.exercises
    sets: int
    reps: int
    weightKg: Optional[float] = None
    restSec: float

class Workout(BaseModel):
    date: str                        # "YYYY-MM-DD"
    name: str
    type: str
    sport: str = "running"
    warmupSec: int = 0
    cooldownSec: int = 0
    blocks: List[Block] = []
    exercises: List[StrengthExercise] = []   # sport in ("strength", "crossfit")
    wodFormat: Optional[str] = None         # crossfit only: "forTime" | "amrap" | "emom"
    wodCapMin: Optional[int] = None         # crossfit amrap: time cap in minutes
    wodMinutes: Optional[int] = None        # crossfit emom: total duration in minutes
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

def build_strength_steps(w: Workout):
    """Strength: sets-of-reps circuit. Crossfit reuses the same shape but
    branches by wodFormat - EMOM maps fairly naturally to a Garmin repeat
    group (N one-minute rounds, each a pass through the exercises); Tabata is
    the same repeat-group/interval+recovery shape build_steps already uses
    for running intervals, just fixed at 8 rounds of 20s work/10s rest per
    exercise (one repeat group per exercise, done sequentially - the classic
    protocol has no per-round rep target, so reps aren't used here). AMRAP has
    no Garmin equivalent (no "as many rounds as possible" step type), so it's
    approximated as a single time-capped interval step - the round breakdown
    lives in the app and the workout name, not something the watch enforces.
    """
    steps = []
    order = 1
    if w.warmupSec:
        steps.append(create_warmup_step(float(w.warmupSec), order)); order += 1

    fmt = w.wodFormat if w.sport == "crossfit" else None
    if fmt == "amrap":
        cap_sec = float((w.wodCapMin or 20) * 60)
        steps.append(create_interval_step(cap_sec, order)); order += 1
    elif fmt == "emom":
        minutes = w.wodMinutes or 12
        group_order = order
        children = []
        child_order = order + 1
        for ex in w.exercises:
            children.append(create_strength_set(ex.category, child_order, 1, ex.reps, 0, weight_kg=ex.weightKg))
            child_order += 3
        steps.append(create_repeat_group(minutes, children, group_order))
        order = child_order
    elif fmt == "tabata":
        for ex in w.exercises:
            group_order = order
            children = [
                create_interval_step(20.0, order + 1),
                create_recovery_step(10.0, order + 2),
            ]
            steps.append(create_repeat_group(8, children, group_order))
            order += 3
    else:
        for ex in w.exercises:
            steps.append(create_strength_set(
                ex.category, order, ex.sets, ex.reps, ex.restSec,
                weight_kg=ex.weightKg,
            ))
            order += 3  # create_strength_set uses order, order+1, order+2 internally

    if w.cooldownSec:  # strength never sets this (no cooldown in that UI); crossfit always does
        steps.append(create_cooldown_step(float(w.cooldownSec), order))
    return steps

# rough seconds-per-meter / seconds-per-rep used only for the required
# duration estimate - mirrored in web/index.html (PACE / ASSUMED_SEC_PER_REP)
_SEC_PER_METER = 0.36
_SEC_PER_REP = 3.5

def _seg_secs(seg: Seg) -> float:
    return seg.value if seg.mode == "time" else seg.value * _SEC_PER_METER

def estimate_secs(w: Workout) -> int:
    if w.sport in ("strength", "crossfit"):
        total = float(w.warmupSec + w.cooldownSec)
        fmt = w.wodFormat if w.sport == "crossfit" else None
        if fmt == "amrap":
            total += (w.wodCapMin or 20) * 60
        elif fmt == "emom":
            total += (w.wodMinutes or 12) * 60
        elif fmt == "tabata":
            total += len(w.exercises) * 8 * (20 + 10)  # 8 rounds of 20s work/10s rest, per exercise
        else:
            for ex in w.exercises:
                total += ex.sets * (ex.reps * _SEC_PER_REP + ex.restSec)
        return int(total)
    total = float(w.warmupSec + w.cooldownSec)
    for b in w.blocks:
        if b.kind == "steady" and b.value:
            total += _seg_secs(Seg(mode=b.mode or "time", value=b.value))
        elif b.kind == "repeat" and b.reps and b.work and b.recovery:
            total += b.reps * (_seg_secs(b.work) + _seg_secs(b.recovery))
    return int(total)

# sport -> (workout class, sportType dict, step-builder). Rowing/elliptical
# reuse build_steps as-is - FitnessEquipmentWorkout only differs from
# RunningWorkout in this top-level sportType tag, not in step shape. Yoga and
# crossfit have no dedicated model in garminconnect.workout (only a SportType
# id each), so they use BaseWorkout directly with an explicit sportType -
# crossfit reuses build_strength_steps (same sets/reps/weight/rest shape as
# strength) tagged as HIIT rather than STRENGTH_TRAINING, since it's circuit/
# conditioning work, not a plain lifting session.
_SPORT_CONFIG = {
    "running": (RunningWorkout, {"sportTypeId": 1, "sportTypeKey": "running"}, build_steps),
    "rowing": (FitnessEquipmentWorkout, {"sportTypeId": 6, "sportTypeKey": "cardio_training"}, build_steps),
    "elliptical": (FitnessEquipmentWorkout, {"sportTypeId": 6, "sportTypeKey": "cardio_training"}, build_steps),
    "strength": (StrengthWorkout, {"sportTypeId": 5, "sportTypeKey": "strength_training"}, build_strength_steps),
    "crossfit": (BaseWorkout, {"sportTypeId": 9, "sportTypeKey": "hiit"}, build_strength_steps),
    "yoga": (BaseWorkout, {"sportTypeId": 7, "sportTypeKey": "yoga"}, build_steps),
}

def build_workout(w: Workout):
    workout_cls, sport_type, step_builder = _SPORT_CONFIG.get(w.sport, _SPORT_CONFIG["running"])
    return workout_cls(
        workoutName=w.name,
        sportType=sport_type,
        estimatedDurationInSecs=estimate_secs(w),
        workoutSegments=[WorkoutSegment(
            segmentOrder=1,
            sportType=sport_type,
            workoutSteps=step_builder(w),
        )],
    )

# ---------- routes ----------

@app.get("/")
def health():
    return {"status": "ok", "service": "maslul-garmin"}

# ---------- Garmin connection management (per user) ----------

class ConnectBody(BaseModel):
    email: str
    password: str

class ConnectTokenBody(BaseModel):
    token: str

@app.post("/garmin/connect")
def garmin_connect(body: ConnectBody, authorization: Optional[str] = Header(default=None)):
    """Email+password connect. Only works for accounts without MFA enabled -
    garminconnect's MFA challenge state lives entirely in one Python object's
    memory (no serializable "resume" token), so it can't be completed across
    two separate stateless HTTP requests the way Vercel functions work. An
    account with MFA gets {"status": "mfa_required"} and should be connected
    via /garmin/connect-token instead (see scripts/generate_token.py).
    """
    user_id = verify_user(authorization)
    client = Garmin(body.email, body.password, return_on_mfa=True)
    try:
        mfa_status, _ = client.login()
    except GarminConnectAuthenticationError:
        raise HTTPException(401, "אימייל או סיסמה שגויים")
    except GarminConnectTooManyRequestsError:
        raise HTTPException(429, "יותר מדי ניסיונות התחברות - נסה שוב בעוד כמה דקות")
    except Exception as e:
        raise HTTPException(502, f"garmin login failed: {_describe_exception(e)}")
    if mfa_status == "needs_mfa":
        return {"status": "mfa_required"}
    token = client.client.dumps()
    save_connection(user_id, token, garmin_email=body.email)
    return {"status": "connected"}

@app.post("/garmin/connect-token")
def garmin_connect_token(body: ConnectTokenBody, authorization: Optional[str] = Header(default=None)):
    """Fallback for MFA accounts: paste a token produced locally by
    scripts/generate_token.py (same script/flow that generated the old
    single-user GARTH_TOKEN, now repurposed to hand the user a per-account
    token to paste in here instead of an env var to set on Vercel)."""
    user_id = verify_user(authorization)
    client = Garmin()
    try:
        client.login(tokenstore=body.token)
    except Exception as e:
        raise HTTPException(400, f"הטוקן לא תקין: {_describe_exception(e)}")
    save_connection(user_id, body.token)
    return {"status": "connected"}

@app.get("/garmin/status")
def garmin_status(authorization: Optional[str] = Header(default=None)):
    user_id = verify_user(authorization)
    row = get_connection(user_id)
    if not row:
        return {"connected": False, "status": "disconnected", "garmin_email": None, "last_sync_at": None}
    return {
        "connected": row["status"] == "connected",
        "status": row["status"],
        "garmin_email": row.get("garmin_email"),
        "last_sync_at": row.get("last_sync_at"),
    }

@app.delete("/garmin/connection")
def garmin_disconnect(authorization: Optional[str] = Header(default=None)):
    user_id = verify_user(authorization)
    disconnect_connection(user_id)
    return {"status": "disconnected"}

# ---------- workout scheduling / activity read-back ----------

@app.post("/schedule-week")
def schedule_week(payload: WeekPayload, authorization: Optional[str] = Header(default=None)):
    user_id = verify_user(authorization)
    try:
        client = get_client_for_user(user_id)
    except NeedsReauth:
        return {"results": [], "error": "needs_reauth"}
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
            # upload_running_workout() (and its per-sport siblings) type-check that
            # the instance matches their one sport before uploading - RunningWorkout
            # only, CyclingWorkout only, etc. build_workout() already produces the
            # right typed class per sport (_SPORT_CONFIG), so go straight through the
            # untyped upload_workout(dict) instead of a sport-specific method - it
            # works for all of them uniformly (every *Workout class shares to_dict()).
            res = client.upload_workout(wk.to_dict())
            wid = res.get("workoutId") if isinstance(res, dict) else res
            client.schedule_workout(wid, w.date)
            results.append({"name": w.name, "date": w.date, "ok": True, "workoutId": wid})
        except Exception as e:
            results.append({"name": w.name, "date": w.date, "ok": False, "error": str(e)})
    mark_synced(user_id)
    return {"results": results}

@app.get("/activities")
def activities(since: str, until: Optional[str] = None, authorization: Optional[str] = Header(default=None)):
    """Completed runs in a date range, for matching back against pushed workouts.
    `workoutId` on the activity (when present) is the same id returned by
    /schedule-week when the structured workout was uploaded, so the frontend
    can match a completed run to its plan entry exactly instead of guessing
    by date/type.
    """
    user_id = verify_user(authorization)
    try:
        client = get_client_for_user(user_id)
    except NeedsReauth:
        return {"activities": [], "error": "needs_reauth"}
    except Exception as e:
        return {"activities": [], "error": f"garmin auth failed: {_describe_exception(e)}"}
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
            # everything below comes free in the same Garmin summary call - no extra request
            "maxHR": a.get("maxHR"),
            "calories": a.get("calories"),
            "elevationGainM": a.get("elevationGain"),
            "elevationLossM": a.get("elevationLoss"),
            "avgCadence": a.get("averageRunningCadenceInStepsPerMinute"),
            "maxCadence": a.get("maxRunningCadenceInStepsPerMinute"),
            "aerobicTrainingEffect": a.get("aerobicTrainingEffect"),
            "anaerobicTrainingEffect": a.get("anaerobicTrainingEffect"),
        })
    return {"activities": out}

@app.get("/activity-splits")
def activity_splits(activityId: str, authorization: Optional[str] = Header(default=None)):
    """Per-km (or per-lap) splits for one completed activity, fetched on demand
    when the user opens a run's detail view - not worth pulling for every activity
    in /activities since it's a separate Garmin request per run.

    The lapDTOs field names below are unverified: garminconnect just proxies
    Garmin Connect's raw JSON here (see get_activity_splits in the installed
    version), which isn't documented anywhere official. If splits come back
    empty on a real account, inspect the raw response shape and adjust the
    key names - this is the same fragility CLAUDE.md warns about for the
    workout step-builder helpers.
    """
    user_id = verify_user(authorization)
    try:
        client = get_client_for_user(user_id)
    except NeedsReauth:
        return {"splits": [], "error": "needs_reauth"}
    except Exception as e:
        return {"splits": [], "error": f"garmin auth failed: {_describe_exception(e)}"}
    try:
        raw = client.get_activity_splits(activityId)
    except Exception as e:
        return {"splits": [], "error": str(e)}
    laps = raw.get("lapDTOs") or raw.get("laps") or []
    splits = []
    for i, lap in enumerate(laps):
        dist_m = lap.get("distance") or 0
        dur_s = lap.get("duration") or lap.get("movingDuration") or 0
        splits.append({
            "index": i + 1,
            "distanceKm": round(dist_m / 1000, 3) if dist_m else None,
            "durationSec": round(dur_s) if dur_s else None,
            "paceSecPerKm": round(dur_s / (dist_m / 1000)) if dist_m and dur_s else None,
            "elevationGainM": lap.get("elevationGain"),
            "elevationLossM": lap.get("elevationLoss"),
            "avgHR": lap.get("averageHR"),
            "maxHR": lap.get("maxHR"),
            "calories": lap.get("calories"),
        })
    return {"splits": splits}
