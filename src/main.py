import logging
import random
import uuid
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

from models import AnswerRecord, Question, SessionData


# --- Configuration ---
class Settings:
    """Centralized configuration for the application."""

    PROJECT_NAME: str = "Lingo"
    DEBUG: bool = False
    LOG_FILE: str = "lingo.log"
    WORDS_FILE: str = "vocabulary/words.csv"
    TEST_SIZE: int = 15
    SESSION_COOKIE_NAME: str = "quiz_session_id"


settings = Settings()

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Persist logs to a rotating file.
file_handler = RotatingFileHandler(settings.LOG_FILE, maxBytes=5_000_000, backupCount=3)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)


# --- Setup ---
app = FastAPI(title=settings.PROJECT_NAME, debug=settings.DEBUG)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- In-memory Storage ---
DUMMY_WORDS: List[Dict[str, str]] = [
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
    """Loads words from the CSV, with a fallback to dummy data."""
    try:
        df = pd.read_csv(settings.WORDS_FILE, encoding="utf-8")
        logger.info(f"Loaded {len(df)} words from {settings.WORDS_FILE}.")
        return df.to_dict("records")
    except FileNotFoundError:
        logger.warning(f"'{settings.WORDS_FILE}' not found. Using dummy data.")
        return DUMMY_WORDS


def get_test_words() -> List[Dict[str, str]]:
    """Selects a random sample of words for a quiz."""
    if not ALL_WORDS:
        return []
    return random.sample(ALL_WORDS, min(settings.TEST_SIZE, len(ALL_WORDS)))


def generate_options(correct_translation: str) -> List[str]:
    """Creates a list of 4 multiple-choice options, one of which is correct."""
    all_translations = {w["translation"] for w in ALL_WORDS}
    all_translations.discard(correct_translation)

    num_options_to_generate = 3
    if len(all_translations) < num_options_to_generate:
        incorrect_options = list(all_translations)
        placeholders = [
            f"Option {i+1}"
            for i in range(num_options_to_generate - len(incorrect_options))
        ]
        incorrect_options.extend(placeholders)
    else:
        incorrect_options = random.sample(
            list(all_translations), num_options_to_generate
        )

    options = [correct_translation] + incorrect_options
    random.shuffle(options)
    return options


def prepare_quiz_data(test_words: List[Dict[str, str]]) -> List[Question]:
    """Pre-generates all questions and their options for a single quiz session."""
    return [
        Question(
            word=item["word"],
            translation=item["translation"],
            options=generate_options(item["translation"]),
        )
        for item in test_words
    ]


# --- Dependencies ---
def get_session_id(
    session_id: Optional[str] = Cookie(None, alias=settings.SESSION_COOKIE_NAME),
) -> Optional[str]:
    """FastAPI dependency to extract the session ID from a cookie."""
    return session_id


# --- Lifecycle Events ---
@app.on_event("startup")
async def startup_event() -> None:
    """Loads the vocabulary from the CSV file when the application starts."""
    global ALL_WORDS
    logger.info("Application startup: loading vocabulary.")
    ALL_WORDS = load_words()
    logger.info("Vocabulary loaded.")


# --- Routes ---
@app.get("/", response_class=RedirectResponse)
async def start_quiz(
    response: Response, session_id: Optional[str] = Depends(get_session_id)
) -> RedirectResponse:
    """
    Handles the start of the quiz.
    If a session cookie exists, it redirects to the first question.
    Otherwise, it creates a new session, sets a cookie, and then redirects.
    """
    if not ALL_WORDS:
        logger.error("Word database is empty. Cannot start quiz.")
        return HTMLResponse("<h1>Error: Word database is empty.</h1>", status_code=500)

    if session_id in sessions:
        logger.info(f"Existing session found: {session_id}. Redirecting.")
        return RedirectResponse(url="/quiz/0", status_code=302)

    new_session_id = str(uuid.uuid4())
    test_words = get_test_words()
    prepared_questions = prepare_quiz_data(test_words)

    sessions[new_session_id] = SessionData(
        prepared_questions=prepared_questions,
        correct_count=0,
        total_questions=len(prepared_questions),
        answers=[],
    )

    logger.info(f"Created new session: {new_session_id}")
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=new_session_id,
        httponly=True,
        samesite="Lax",
    )

    return RedirectResponse(url="/quiz/0", status_code=302, headers=response.headers)


@app.get("/api/quiz/{index}")
async def get_question_data(
    index: int, session_id: str = Depends(get_session_id)
) -> Dict[str, Any]:
    """API endpoint to fetch data for a single quiz question."""
    session_data = sessions.get(session_id)
    if not session_data:
        return JSONResponse({"error": "Session invalid"}, status_code=401)

    if not (0 <= index < session_data.total_questions):
        return JSONResponse({"error": "Question index out of bounds"}, status_code=404)

    current_q_data = session_data.prepared_questions[index]
    answer_record = (
        session_data.answers[index] if index < len(session_data.answers) else None
    )

    return {
        "word": current_q_data.word,
        "options": current_q_data.options,
        "current_index": index,
        "total_questions": session_data.total_questions,
        "answer_record": answer_record,
    }


@app.get("/quiz/{index}", response_class=HTMLResponse)
async def display_question_page(
    request: Request, index: int, session_id: str = Depends(get_session_id)
) -> HTMLResponse:
    """
    Displays the main quiz page.
    This route serves the HTML skeleton. The page then uses JavaScript
    to fetch the question data from the `/api/quiz/{index}` endpoint.
    """
    session_data = sessions.get(session_id)

    if not session_data:
        return RedirectResponse(url="/", status_code=302)
    if index >= session_data.total_questions:
        return RedirectResponse(url="/result", status_code=302)

    return templates.TemplateResponse(
        "index.html", {"request": request, "current_index": index}
    )


@app.post("/submit_answer", response_model=AnswerRecord)
async def submit_answer(
    answer: str = Form(...),
    current_index: int = Form(...),
    session_id: str = Depends(get_session_id),
) -> AnswerRecord:
    """
    Accepts a user's answer submission via AJAX.
    It validates the answer, updates the session score, and records the
    result. Prevents re-submission for an already answered question.
    """
    session_data = sessions.get(session_id)
    if not session_data or not (0 <= current_index < session_data.total_questions):
        return JSONResponse({"error": "Invalid session or index"}, status_code=401)

    if current_index < len(session_data.answers):
        return JSONResponse({"error": "Question already answered"}, status_code=400)

    current_q = session_data.prepared_questions[current_index]
    is_correct = answer == current_q.translation

    if is_correct:
        session_data.correct_count += 1

    logger.info(
        f"Session {session_id} Q{current_index}: Answer for '{current_q.word}' "
        f"was {'CORRECT' if is_correct else 'INCORRECT'}."
    )

    record = AnswerRecord(
        word=current_q.word,
        user_answer=answer,
        correct_answer=current_q.translation,
        is_correct=is_correct,
        attempted=True,
    )
    session_data.answers.append(record)

    return record


@app.get("/api/result")
async def get_result_data(
    session_id: str = Depends(get_session_id),
) -> Dict[str, Any]:
    """API endpoint to get result data for the session."""
    session_data = sessions.get(session_id)
    if not session_data:
        return JSONResponse({"error": "Session invalid"}, status_code=401)

    score = (
        round((session_data.correct_count / session_data.total_questions) * 100)
        if session_data.total_questions > 0
        else 0
    )

    return {
        "correct_count": session_data.correct_count,
        "total_questions": session_data.total_questions,
        "score_percentage": score,
        "answers": session_data.answers,
    }


@app.get("/result", response_class=HTMLResponse)
async def result_page(request: Request) -> HTMLResponse:
    """Serves the result page skeleton."""
    return templates.TemplateResponse("result.html", {"request": request})


@app.post("/api/reset")
async def reset_session(
    response: Response, session_id: str = Depends(get_session_id)
) -> Dict[str, str]:
    """Resets the quiz session by clearing the session data and cookie."""
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"Session {session_id} has been reset.")

    response.delete_cookie(settings.SESSION_COOKIE_NAME)

    return {"status": "success", "message": "Session reset successfully."}


# --- Main ---
if __name__ == "__main__":
    logger.info("Starting application server.")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
    )
