import pandas as pd
import random
import uuid
import logging  # Import the logging module
from fastapi import (
    FastAPI,
    Request,
    Form,
    Response,
    Cookie,
    Depends,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Optional, Any
from fastapi.staticfiles import StaticFiles

# --- Logging Configuration ---
# Configure basic logging settings (console)
logging.basicConfig(
    level=logging.INFO,  # Set the minimum level to INFO
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Create a module logger
logger = logging.getLogger(__name__)

# Also add a rotating file handler so logs are persisted to disk
from logging.handlers import RotatingFileHandler

LOG_FILE = "lingo.log"
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)


# --- Configuration ---
app = FastAPI()

# Mount static files directory to serve CSS/JS.
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
WORDS_FILE = "vocabulary/words.csv"
TEST_SIZE = 15

# Global storage for quiz data and session management.
ALL_WORDS: List[Dict[str, str]] = []
# Key is the unique session ID (from cookie), Value is the quiz state
user_sessions: Dict[str, Dict] = {}
SESSION_COOKIE_NAME = "quiz_session_id"  # Define the cookie name


# --- Core Logic Functions ---
def load_words() -> List[Dict[str, str]]:
    """Loads the word list from the CSV file, with a dummy data fallback."""
    try:
        df = pd.read_csv(WORDS_FILE, encoding="utf-8")
        logger.info(f"Loaded {len(df)} words from {WORDS_FILE}.")
        return df.to_dict("records")
    except FileNotFoundError:
        logger.warning(f"File {WORDS_FILE} not found. Using dummy data.")
        # Fallback dummy data structure if file is missing
        dummy_data = {
            "word": ["Hund", "Katze", "Baum", "Haus", "Wasser"],
            "translation": ["dog", "cat", "tree", "house", "water"],
        }
        df_dummy = pd.DataFrame(dummy_data)
        return df_dummy.to_dict("records")


def get_test_words() -> List[Dict[str, str]]:
    """Randomly selects TEST_SIZE words for the quiz."""
    if not ALL_WORDS:
        return []
    return random.sample(ALL_WORDS, min(TEST_SIZE, len(ALL_WORDS)))


def generate_options(
    correct_translation: str, all_words: List[Dict[str, str]]
) -> List[str]:
    """Generates four options (one correct, three wrong) for a given word."""
    if not all_words:
        return [correct_translation]

    incorrect_translations = [
        w["translation"] for w in all_words if w["translation"] != correct_translation
    ]

    # Handle cases where fewer than 3 unique incorrect options exist
    if len(incorrect_translations) < 3:
        wrong_options = incorrect_translations
        while len(wrong_options) < 3:
            # Append generic options if not enough real translations exist
            wrong_options.append(f"Option {len(wrong_options) + 1}")
    else:
        wrong_options = random.sample(incorrect_translations, 3)

    options = [correct_translation] + wrong_options
    random.shuffle(options)
    return options


def prepare_quiz_data(
    test_words: List[Dict[str, str]], all_words: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Pre-generates options for all questions for session consistency."""
    prepared_questions = []
    for item in test_words:
        correct_translation = item["translation"]
        options = generate_options(correct_translation, all_words)

        prepared_questions.append(
            {
                "word": item["word"],
                "translation": correct_translation,
                "options": options,
            }
        )
    return prepared_questions


# --- Dependency to retrieve session ID from cookie ---
def get_session_id(session_id: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME)):
    """Retrieves the session ID from the cookie."""
    return session_id


# --- Application Startup Event ---
@app.on_event("startup")
async def startup_event():
    """Load vocabulary data when the application starts."""
    global ALL_WORDS
    logger.info("Application starting up. Loading vocabulary data...")
    ALL_WORDS = load_words()
    logger.info("Vocabulary data loaded successfully.")


# --- Routes ---
@app.get("/", response_class=RedirectResponse)
async def start_quiz(
    response: Response, session_id: Optional[str] = Depends(get_session_id)
):
    """
    Initializes the quiz session, sets the cookie, and redirects.
    If a valid cookie exists, just redirects to the quiz start.
    """
    logger.info(f"Accessing root path. Current session_id: {session_id}")

    if not ALL_WORDS:
        logger.error("Word database is empty. Cannot start quiz.")
        return HTMLResponse("<h1>Error: Word database is empty.</h1>", status_code=500)

    # Check if session is already active and valid
    if session_id in user_sessions:
        logger.info(f"Existing session found: {session_id}. Redirecting to /quiz/0.")
        return RedirectResponse(url="/quiz/0", status_code=302)

    # --- New Session Initialization ---
    new_session_id = str(uuid.uuid4())  # Generate a unique ID

    test_words = get_test_words()
    prepared_questions = prepare_quiz_data(test_words, ALL_WORDS)

    # Initialize the new quiz session state
    user_sessions[new_session_id] = {
        "prepared_questions": prepared_questions,
        "correct_count": 0,
        "total_questions": len(test_words),
        "answers": [],
    }

    logger.info(
        f"Creating NEW session ID: {new_session_id} with {len(test_words)} questions."
    )

    # Set the session ID cookie on the response
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_session_id,
        httponly=True,  # Security measure: prevents client-side JS access
        samesite="Lax",
    )

    # Redirect to the first question (index 0)
    return RedirectResponse(url="/quiz/0", status_code=302, headers=response.headers)


@app.get("/quiz/{index}", response_class=HTMLResponse)
async def display_question(
    request: Request, index: int, session_id: str = Depends(get_session_id)
):
    """Displays a specific question by index, requiring a valid session ID."""

    session_data = user_sessions.get(session_id)

    # Redirect to start if session is missing or invalid
    if not session_data:
        logger.warning(
            f"Invalid or missing session ID: {session_id}. Redirecting to /."
        )
        return RedirectResponse(url="/", status_code=302)

    total_questions = session_data["total_questions"]

    # Redirect to results if index is out of bounds
    if index >= total_questions or index < 0:
        logger.warning(
            f"Session {session_id}: Index {index} out of bounds (Total: {total_questions}). Redirecting to /result."
        )
        return RedirectResponse(url="/result", status_code=302)

    current_q_data = session_data["prepared_questions"][index]

    logger.info(
        f"Session {session_id} viewing question {index + 1}/{total_questions}: {current_q_data['word']}"
    )

    # Check if this question has been answered to display feedback
    answer_record = None
    if index < len(session_data["answers"]):
        answer_record = session_data["answers"][index]

    context = {
        "request": request,
        "word": current_q_data["word"],
        "options": current_q_data["options"],
        "current_index": index,
        "total_questions": total_questions,
        "correct_translation": current_q_data["translation"],
        "answer_record": answer_record,
        "session_id": session_id,  # Ensure session_id is passed for debugging
        "is_first_question": index == 0,
        "is_last_question": index == total_questions - 1,
    }

    return templates.TemplateResponse("index.html", context)


@app.post("/submit_answer", response_class=JSONResponse)
async def submit_answer(
    answer: str = Form(...),
    current_index: int = Form(...),
    session_id: str = Depends(get_session_id),
):
    """Processes the user's AJAX answer using the session ID from the cookie."""

    session_data = user_sessions.get(session_id)

    if not session_data or current_index >= session_data["total_questions"]:
        logger.error(
            f"Submit failed: Invalid session {session_id} or index {current_index}."
        )
        return JSONResponse(
            {"error": "Invalid session or index. Please restart the quiz."},
            status_code=401,
        )

    # Prevent re-submission
    if current_index < len(session_data["answers"]):
        logger.warning(
            f"Session {session_id}: Question {current_index} already answered."
        )
        return JSONResponse(
            {"error": "Answer already recorded for this question."}, status_code=400
        )

    current_q_data = session_data["prepared_questions"][current_index]
    correct_translation = current_q_data["translation"]

    # Get the word from session data
    word_from_session = current_q_data["word"]

    is_correct = answer == correct_translation

    if is_correct:
        session_data["correct_count"] += 1
        log_result = "CORRECT"
    else:
        log_result = "INCORRECT"

    logger.info(
        f"Session {session_id} submitted answer for Q{current_index}: "
        f"'{word_from_session}' -> '{answer}'. Result: {log_result}."
    )

    # Record the new answer
    record = {
        "word": word_from_session,
        "user_answer": answer,
        "correct_answer": correct_translation,
        "is_correct": is_correct,
        "attempted": True,
    }
    session_data["answers"].append(record)

    # Return the record data for client-side feedback
    return JSONResponse(record)


# --- Result Route ---
@app.get("/result", response_class=HTMLResponse)
async def show_result(request: Request, session_id: str = Depends(get_session_id)):
    """Displays the final quiz result page, requiring a valid session ID."""

    session_data = user_sessions.get(session_id)

    if not session_data:
        logger.warning(
            f"Attempt to view result with missing session ID: {session_id}. Redirecting."
        )
        # Redirect to start if session is missing
        return RedirectResponse(url="/", status_code=302)

    correct_count = session_data["correct_count"]
    total_questions = session_data["total_questions"]
    final_score = f"{correct_count}/{total_questions}"

    # Redirect to the last unanswered question if the quiz isn't finished
    if len(session_data["answers"]) < total_questions:
        last_unanswered_index = len(session_data["answers"])
        logger.warning(
            f"Session {session_id}: Quiz incomplete. Redirecting to Q{last_unanswered_index}."
        )
        return RedirectResponse(url=f"/quiz/{last_unanswered_index}", status_code=302)

    score_percentage = (
        int((correct_count / total_questions) * 100) if total_questions else 0
    )

    context = {
        "request": request,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "score_percentage": score_percentage,
        "answers": session_data["answers"],
    }

    # Clear the session cookie and data after showing results (cleanup)
    response = templates.TemplateResponse("result.html", context)
    response.delete_cookie(SESSION_COOKIE_NAME)

    # Remove data from global storage
    if session_id in user_sessions:
        del user_sessions[session_id]
        logger.info(
            f"Session {session_id} finished quiz with score {final_score}. Session data and cookie cleared."
        )

    return response


# --- Run Application ---
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting uvicorn server...")
    # Standard entry point for running the application using uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
