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
