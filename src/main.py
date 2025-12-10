import logging
import os
import random
import uuid
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Any

import pandas as pd
import uvicorn
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    Request,
    Response,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


class Question(BaseModel):
    word: str
    translation: str
    options: List[str]


class SessionData(BaseModel):
    prepared_questions: List[Question]
    correct_count: int
    total_questions: int
    answers: List[Dict[str, Any]]
    created_at: datetime  # Tracks when the session started


class AnswerRecord(BaseModel):
    word: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    attempted: bool


# --- Configuration ---
class Settings:
    """Centralized configuration for the application."""

    PROJECT_NAME: str = "wlingo"
    DEBUG: bool = False
    LOG_DIR: str = "log"
    LOG_FILE: str = "wlingo.log"
    WORDS_FILE: str = "vocabulary/words.csv"
    TEST_SIZE: int = 15
    SESSION_COOKIE_NAME: str = "quiz_session_id"
    SESSION_TIMEOUT_MINUTES: int = 120  # 2 hours


settings = Settings()

# --- Logging Setup ---
# 1. Create log directory if it doesn't exist
if not os.path.exists(settings.LOG_DIR):
    os.makedirs(settings.LOG_DIR)

# 2. Construct full log path
log_path = os.path.join(settings.LOG_DIR, settings.LOG_FILE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 3. Use the new path in the file handler
file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(file_handler)


# --- App Setup ---
app = FastAPI(title=settings.PROJECT_NAME, debug=settings.DEBUG)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Storage ---
DUMMY_WORDS = [
    {"word": "Hund", "translation": "dog"},
    {"word": "Katze", "translation": "cat"},
    {"word": "Baum", "translation": "tree"},
    {"word": "Haus", "translation": "house"},
    {"word": "Wasser", "translation": "water"},
]
ALL_WORDS: List[Dict[str, str]] = []
sessions: Dict[str, SessionData] = {}


# --- Core Logic ---
def load_words() -> List[Dict[str, str]]:
    """Loads vocabulary from CSV or falls back to dummy data."""
    try:
        df = pd.read_csv(settings.WORDS_FILE, encoding="utf-8")
        logger.info(f"Loaded {len(df)} words.")
        return df.to_dict("records")
    except FileNotFoundError:
        logger.warning("CSV not found, using dummy data.")
        return DUMMY_WORDS


def get_test_words() -> List[Dict[str, str]]:
    """Selects a random subset of words for the quiz."""
    if not ALL_WORDS:
        return []
    return random.sample(ALL_WORDS, min(settings.TEST_SIZE, len(ALL_WORDS)))


def generate_options(correct_translation: str) -> List[str]:
    """Generates 4 options including the correct answer."""
    all_translations = {w["translation"] for w in ALL_WORDS}
    all_translations.discard(correct_translation)

    # Ensure we have at least 3 wrong options
    incorrect_options = list(all_translations)
    while len(incorrect_options) < 3:
        incorrect_options.append(f"Option {len(incorrect_options)+1}")

    options = [correct_translation] + random.sample(incorrect_options, 3)
    random.shuffle(options)
    return options


def prepare_quiz_data(test_words: List[Dict[str, str]]) -> List[Question]:
    """Generates Questions objects for the session."""
    return [
        Question(
            word=item["word"],
            translation=item["translation"],
            options=generate_options(item["translation"]),
        )
        for item in test_words
    ]


def get_active_session(session_id: str) -> Optional[SessionData]:
    """Retrieves a session if it exists and hasn't expired."""
    if not session_id or session_id not in sessions:
        return None

    session = sessions[session_id]

    # Check timeout
    if datetime.now() - session.created_at > timedelta(
        minutes=settings.SESSION_TIMEOUT_MINUTES
    ):
        logger.info(
            f"Session {session_id} expired (created at {session.created_at}). Deleting."
        )
        del sessions[session_id]
        return None

    return session


# --- Dependencies ---
def get_session_id(
    session_id: Optional[str] = Cookie(None, alias=settings.SESSION_COOKIE_NAME),
) -> Optional[str]:
    return session_id


# --- Lifecycle ---
@app.on_event("startup")
async def startup_event():
    global ALL_WORDS
    ALL_WORDS = load_words()


# 1. NEW: The Landing Page
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serves the welcome page."""
    return templates.TemplateResponse("start.html", {"request": request})


# 2. MODIFIED: Create Session and Redirect
@app.post("/start", response_class=RedirectResponse)
async def start_quiz_session(response: Response):
    """
    Creates a new session, sets the cookie, and redirects to Q0.
    """
    if not ALL_WORDS:
        # Determine how to handle error (e.g. redirect to error page)
        return RedirectResponse(url="/", status_code=302)

    # Initialize Session
    new_id = str(uuid.uuid4())
    test_words = get_test_words()
    prepared_questions = prepare_quiz_data(test_words)

    sessions[new_id] = SessionData(
        prepared_questions=prepared_questions,
        correct_count=0,
        total_questions=len(prepared_questions),
        answers=[],
        created_at=datetime.now(),  # Set creation time
    )

    logger.info(f"New session started: {new_id}")

    # Create the redirect response
    redirect = RedirectResponse(url="/quiz/0", status_code=302)

    # Set the cookie on the redirect response
    redirect.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=new_id,
        httponly=True,
        samesite="Lax",
    )

    return redirect


@app.get("/api/quiz/{index}")
async def get_question_data(index: int, session_id: str = Depends(get_session_id)):
    """Returns JSON data for a specific question."""
    session_data = get_active_session(session_id)
    if not session_data:
        return JSONResponse({"error": "Session invalid or expired"}, status_code=401)

    if not (0 <= index < session_data.total_questions):
        return JSONResponse({"error": "Index out of bounds"}, status_code=404)

    current_q = session_data.prepared_questions[index]
    # Return answer record if it exists (for review/history)
    record = session_data.answers[index] if index < len(session_data.answers) else None

    return {
        "word": current_q.word,
        "options": current_q.options,
        "current_index": index,
        "total_questions": session_data.total_questions,
        "answer_record": record,
    }


@app.get("/quiz/{index}", response_class=HTMLResponse)
async def display_question_page(
    request: Request, index: int, session_id: str = Depends(get_session_id)
):
    """Serves the HTML shell for the quiz question."""
    session_data = get_active_session(session_id)
    if not session_data:
        return RedirectResponse(url="/", status_code=302)
    if index >= session_data.total_questions:
        return RedirectResponse(url="/result", status_code=302)

    return templates.TemplateResponse(
        "quiz.html", {"request": request, "current_index": index}
    )


@app.post("/submit_answer", response_model=AnswerRecord)
async def submit_answer(
    selected_option_index: int = Form(...),  # Accepts Integer Index
    current_index: int = Form(...),
    session_id: str = Depends(get_session_id),
):
    """
    Validates answer index, looks up string value, and records result.
    """
    session_data = get_active_session(session_id)

    # 1. Validate Session
    if not session_data or not (0 <= current_index < session_data.total_questions):
        return JSONResponse(
            {"error": "Invalid session, expired, or index error"}, status_code=401
        )

    # 2. Prevent Double Submission
    if current_index < len(session_data.answers):
        return JSONResponse({"error": "Already answered"}, status_code=400)

    current_q = session_data.prepared_questions[current_index]

    # 3. Validate Option Index
    if not (0 <= selected_option_index < len(current_q.options)):
        return JSONResponse({"error": "Invalid option index"}, status_code=400)

    # 4. Lookup String & Check Answer
    user_answer_str = current_q.options[selected_option_index]
    is_correct = user_answer_str == current_q.translation

    if is_correct:
        session_data.correct_count += 1

    logger.info(
        f"Session {session_id} Q{current_index}: Selected idx {selected_option_index} "
        f"('{user_answer_str}') -> {'CORRECT' if is_correct else 'INCORRECT'}"
    )

    # 5. Record Result
    record = AnswerRecord(
        word=current_q.word,
        user_answer=user_answer_str,
        correct_answer=current_q.translation,
        is_correct=is_correct,
        attempted=True,
    )
    session_data.answers.append(record)

    return record


@app.get("/api/result")
async def get_result_data(session_id: str = Depends(get_session_id)):
    """Returns JSON stats for the completed quiz."""
    session_data = get_active_session(session_id)
    if not session_data:
        return JSONResponse({"error": "Session invalid or expired"}, status_code=401)

    total = session_data.total_questions
    score = round((session_data.correct_count / total) * 100) if total > 0 else 0

    return {
        "correct_count": session_data.correct_count,
        "total_questions": total,
        "score_percentage": score,
        "answers": session_data.answers,
    }


@app.get("/result", response_class=HTMLResponse)
async def result_page(request: Request):
    """Serves the HTML shell for results."""
    return templates.TemplateResponse("result.html", {"request": request})


@app.post("/api/reset")
async def reset_session(response: Response, session_id: str = Depends(get_session_id)):
    """Clears session data and cookie."""
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"Reset session: {session_id}")

    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
