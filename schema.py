from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime

# ── Shared helper ─────────────────────────────────────────
class PyObjectId(str):
    """Converts MongoDB ObjectId to plain string for JSON responses."""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    @classmethod
    def validate(cls, v):
        from bson import ObjectId
        if not ObjectId.is_valid(str(v)):
            raise ValueError("Invalid ObjectId")
        return str(v)

# ══════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════
class RegisterRequest(BaseModel):
    name:     str        = Field(..., min_length=2)
    email:    EmailStr
    password: str        = Field(..., min_length=6)

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      str
    name:         str

class UserResponse(BaseModel):
    id:         str
    name:       str
    email:      str
    created_at: datetime

# ══════════════════════════════════════════════════════════
#  EXERCISES
# ══════════════════════════════════════════════════════════
MUSCLE_GROUPS = ["chest", "back", "biceps", "triceps", "legs", "shoulders", "abs", "cardio"]

class ExerciseCreate(BaseModel):
    muscle:    str  = Field(..., description="e.g. chest")
    name:      str  = Field(..., min_length=2)
    emoji:     str  = Field(default="🏋️")
    image_url: Optional[str] = None

class ExerciseUpdate(BaseModel):
    name:      Optional[str] = None
    emoji:     Optional[str] = None
    image_url: Optional[str] = None

class ExerciseResponse(BaseModel):
    id:         str
    muscle:     str
    name:       str
    emoji:      str
    image_url:  Optional[str]
    created_at: datetime

# ══════════════════════════════════════════════════════════
#  SESSIONS
# ══════════════════════════════════════════════════════════
class SetIn(BaseModel):
    set_number: int
    weight_kg:  float = Field(..., ge=0)
    reps:       int   = Field(..., ge=1)

class SessionCreate(BaseModel):
    exercise_id: str
    date:        Optional[datetime] = None   # defaults to now if omitted
    sets:        List[SetIn]        = Field(..., min_items=1)
    notes:       Optional[str]      = None

class SessionUpdate(BaseModel):
    sets:  Optional[List[SetIn]] = None
    notes: Optional[str]         = None

class SetOut(BaseModel):
    set_number: int
    weight_kg:  float
    reps:       int

class SessionResponse(BaseModel):
    id:          str
    exercise_id: str
    date:        datetime
    sets:        List[SetOut]
    notes:       Optional[str]
    created_at:  datetime

# ══════════════════════════════════════════════════════════
#  PROGRESS
# ══════════════════════════════════════════════════════════
class WeightDataPoint(BaseModel):
    date:      datetime
    max_weight: float   # heaviest weight lifted that session

class ExerciseProgress(BaseModel):
    exercise_id:   str
    exercise_name: str
    emoji:         str
    personal_best: float
    history:       List[WeightDataPoint]

class MuscleStats(BaseModel):
    muscle:           str
    total_sessions:   int
    total_sets:       int
    last_trained:     Optional[datetime]

class OverallStats(BaseModel):
    total_sessions:   int
    total_sets:       int
    total_exercises:  int
    prs_this_month:   int
    current_streak:   int   # consecutive days with a session
    muscle_breakdown: List[MuscleStats]

# ══════════════════════════════════════════════════════════
#  CHAT
# ══════════════════════════════════════════════════════════
class ChatMessage(BaseModel):
    role:    str   # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    message:  str
    history:  List[ChatMessage] = []   # full conversation so far