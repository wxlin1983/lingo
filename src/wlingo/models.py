from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Any

from pydantic import BaseModel


# --- Models ---
class Question(BaseModel):
    word: str
    translation: str
    options: List[str]


class SessionData(BaseModel):
    prepared_questions: List[Question]
    correct_count: int
    total_questions: int
    answers: List["AnswerRecord"]
    created_at: datetime
    topic: str
    mode: str = "standard"


class AnswerRecord(BaseModel):
    word: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    attempted: bool
