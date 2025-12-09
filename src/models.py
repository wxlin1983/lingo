from pydantic import BaseModel
from typing import List, Dict, Optional, Any


class Question(BaseModel):
    word: str
    translation: str
    options: List[str]


class SessionData(BaseModel):
    prepared_questions: List[Question]
    correct_count: int
    total_questions: int
    answers: List[Dict[str, Any]]


class AnswerRecord(BaseModel):
    word: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    attempted: bool
