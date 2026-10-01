"""
Shared Pydantic models for the workout data model (matches buildPayload in
web/index.html - see CLAUDE.md's "Workout data model" section). Split out of
index.py so coach.py can import Workout without a circular dependency
(index.py registers routes from both index.py and coach.py; coach.py needs
Workout to validate what the AI coach proposes).
"""

from typing import List, Literal, Optional

from pydantic import BaseModel


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


# ---------- AI coach chat (server/api/coach.py) ----------
# Kept here rather than in coach.py so index.py can import the request model
# (needed at route-registration time) without importing coach.py itself at
# module load - coach.py pulls in the anthropic package, and every route
# shares one warm Lambda process, so an eagerly-imported heavy/optional
# dependency would run on every cold start regardless of which route is hit.
# index.py instead imports coach.run_chat lazily, inside the /coach/chat
# handler, so anthropic is only ever touched by a request that actually needs it.

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class CoachContext(BaseModel):
    """Loose by design (plain dicts, not the full Workout model) - this only
    ever gets formatted into prompt text, never parsed back, so it doesn't
    need to be kept in lockstep with the strict schema the way the tool
    output does."""
    profile: dict = {}
    upcomingRace: Optional[dict] = None
    weekWorkouts: List[dict] = []   # [{date, workouts: [...]}, ...] for the visible week
    recentStats: dict = {}          # this/last/two-weeks-ago planned+done km, month totals

class CoachChatBody(BaseModel):
    messages: List[ChatMessage]
    context: CoachContext

class ProposedDayChange(BaseModel):
    date: str
    workouts: List[Workout]

class CoachChatResponse(BaseModel):
    reply: str
    proposedChanges: Optional[List[ProposedDayChange]] = None
