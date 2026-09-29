"""
AI coach chat: lets the athlete describe how they actually feel ("my knee
hurts", "I'm exhausted this week") in free text and get a response from
Claude - either plain advice, or a concrete proposed change to this week's
plan (via tool use), which the frontend shows as a preview the athlete must
explicitly approve before it touches S.plan (same approve-before-apply
pattern as the auto-generate flow - see CLAUDE.md's "UI conventions").

Model: claude-sonnet-5-5 (chosen over Opus for cost - this is a personal app
and the owner opted for the cheaper tier). Requires ANTHROPIC_API_KEY on the
server (separate from all the Supabase/Garmin env vars) - billed to whoever's
Anthropic account owns that key. Like GARMIN_TOKEN_ENCRYPTION_KEY, this is
the app owner's key, shared across every user of the app, not per-user - see
CLAUDE.md's "AI coach" section.

The proposed-changes tool is deliberately NOT `strict: true` with a hand-
written exhaustive JSON schema - instead its input is validated against the
same `Workout` Pydantic model /schedule-week already uses (server/api/models.py),
so there's exactly one definition of what a valid workout looks like. A tool
call that fails validation is dropped silently from the reply (the
conversational text still comes through) rather than ever reaching the
frontend as a malformed "apply this" proposal.
"""

import os
from typing import List, Literal, Optional

import anthropic
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

try:
    from models import Workout
except ImportError:
    from .models import Workout

MODEL = "claude-sonnet-5-5"


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY env var is not set on the server")
    return anthropic.Anthropic()


# ---------- request/response models ----------

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


# ---------- system prompt ----------

_SYSTEM_TEMPLATE = """You are the coaching assistant inside Maslul (מסלול), a personal running \
training-planner app. The athlete is chatting with you directly - they may describe how they \
feel physically (injury, pain, fatigue, illness, great and want to push harder, short on time, \
travel, weather, anything), ask about their plan, or just want advice.

Reply in Hebrew unless the athlete writes in English. Keep the tone like a knowledgeable, \
approachable coach, not a medical professional - for anything that sounds like it needs actual \
medical attention (sharp/persistent pain, symptoms of illness beyond normal fatigue), say so \
plainly and recommend they see a doctor or physio, in addition to any training adjustment.

Athlete context (current as of this message):
```json
{context_json}
```

Workout data model, for when you propose changes: `sport` is one of running/rowing/elliptical/ \
strength/crossfit/yoga. `type` is the sub-kind for cardio sports (intervals/tempo/hills/fartlek/ \
volume/recovery/race) - for strength/crossfit/yoga, `type` equals `sport`. Cardio sports use \
`blocks` (a list of `{{kind:"steady", mode:"time"|"dist", value}}` or \
`{{kind:"repeat", reps, work:{{mode,value}}, recovery:{{mode,value}}}}`, value in seconds for \
time / meters for dist) and leave `exercises` empty. Strength/crossfit use `exercises` \
(`{{category, sets, reps, weightKg, restSec}}`, category is a Garmin exercise key like "SQUAT") \
and leave `blocks` empty.

When you want to actually change one or more days of the plan, call `propose_plan_changes` - \
each entry's `workouts` list REPLACES everything currently on that date, so include every \
workout that date should end up with, not just the new one. Only call it when you're proposing a \
concrete, ready-to-apply change; for general advice or when you need more information first, \
just reply in text and ask. Never propose a date outside the week shown in weekWorkouts above. \
If the athlete describes an injury, default to caution: reduce volume/intensity, swap to lower- \
impact cross-training, or suggest rest, rather than proposing they push through pain."""

def build_system_prompt(context: CoachContext) -> str:
    return _SYSTEM_TEMPLATE.format(context_json=context.model_dump_json(indent=2))


# ---------- tool definition ----------

_SEG_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["time", "dist"]},
        "value": {"type": "integer", "description": "seconds if time, meters if dist"},
    },
    "required": ["mode", "value"],
}

_BLOCK_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["repeat", "steady"]},
        "reps": {"type": "integer"},
        "work": _SEG_SCHEMA,
        "recovery": _SEG_SCHEMA,
        "mode": {"type": "string", "enum": ["time", "dist"]},
        "value": {"type": "integer"},
    },
    "required": ["kind"],
}

_EXERCISE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "description": "Garmin exercise category key, e.g. SQUAT, PUSH_UP, PLANK"},
        "sets": {"type": "integer"},
        "reps": {"type": "integer"},
        "weightKg": {"type": "number"},
        "restSec": {"type": "number"},
    },
    "required": ["category", "sets", "reps", "restSec"],
}

_WORKOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "sport": {"type": "string", "enum": ["running", "rowing", "elliptical", "strength", "crossfit", "yoga"]},
        "warmupSec": {"type": "integer"},
        "cooldownSec": {"type": "integer"},
        "blocks": {"type": "array", "items": _BLOCK_SCHEMA},
        "exercises": {"type": "array", "items": _EXERCISE_SCHEMA},
    },
    "required": ["date", "name", "type", "sport"],
}

PROPOSE_PLAN_TOOL = {
    "name": "propose_plan_changes",
    "description": (
        "Propose a concrete change to one or more days of this week's training plan. "
        "Each date's workouts list fully replaces that day's current plan."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "YYYY-MM-DD, must be one of the dates in weekWorkouts"},
                        "workouts": {"type": "array", "items": _WORKOUT_SCHEMA},
                    },
                    "required": ["date", "workouts"],
                },
            },
        },
        "required": ["changes"],
    },
}


# ---------- the actual call ----------

def run_chat(body: CoachChatBody) -> CoachChatResponse:
    client = _client()
    system_prompt = build_system_prompt(body.context)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            tools=[PROPOSE_PLAN_TOOL],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=messages,
        )
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"coach request failed: {e}")
    except anthropic.APIConnectionError as e:
        raise HTTPException(502, f"could not reach the coach: {e}")

    if response.stop_reason == "refusal":
        return CoachChatResponse(reply="מצטער, לא הצלחתי לענות על ההודעה הזו. נסה לנסח אחרת.")

    reply_parts = [b.text for b in response.content if b.type == "text" and b.text]
    reply = "\n".join(reply_parts).strip()

    # the model is told in the system prompt to only propose dates already
    # shown in weekWorkouts, but that's a prompt instruction, not a guarantee -
    # enforce it here too rather than letting a hallucinated date slip through
    # to the frontend as an applyable change.
    valid_dates = {d.get("date") for d in body.context.weekWorkouts}

    proposed: List[ProposedDayChange] = []
    for block in response.content:
        if block.type != "tool_use" or block.name != "propose_plan_changes":
            continue
        for change in block.input.get("changes", []):
            date = change.get("date")
            if date not in valid_dates:
                reply += f"\n\n(התעלמתי מהצעה לתאריך {date} - מחוץ לשבוע המוצג)"
                continue
            try:
                workouts = [Workout(**w) for w in change.get("workouts", [])]
            except ValidationError:
                reply += f"\n\n(לא הצלחתי לבנות את ההצעה עבור {date}: פורמט לא תקין)"
                continue
            proposed.append(ProposedDayChange(date=date, workouts=workouts))

    return CoachChatResponse(reply=reply or "...", proposedChanges=proposed or None)
