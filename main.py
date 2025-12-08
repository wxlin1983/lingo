import pandas as pd
import random
import json
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Optional, Any

# from urllib.parse import quote # Unused, removed for clean up

# --- Configuration ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
WORDS_FILE = "words.csv"
TEST_SIZE = 15

# Global storage for quiz data and session management
ALL_WORDS: List[Dict[str, str]] = []
user_sessions: Dict[str, Dict] = {}
SESSION_ID = "test_session"


# --- Core Logic Functions (Kept original logic) ---


def load_words() -> List[Dict[str, str]]:
    """Loads the word list from the CSV file."""
    try:
        df = pd.read_csv(WORDS_FILE, encoding="utf-8")
        return df.to_dict("records")
    except FileNotFoundError:
        print(f"ERROR: File {WORDS_FILE} not found. Using dummy data.")
        # Fallback dummy data structure
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
    """Generates four options (one correct, three wrong) for a given translation."""
    if not all_words:
        return [correct_translation]

    incorrect_translations = [
        w["translation"] for w in all_words if w["translation"] != correct_translation
    ]

    if len(incorrect_translations) < 3:
        # If not enough incorrect options exist, pad with placeholders
        wrong_options = incorrect_translations
        while len(wrong_options) < 3:
            wrong_options.append(f"Placeholder {len(wrong_options)}")
    else:
        wrong_options = random.sample(incorrect_translations, 3)

    options = [correct_translation] + wrong_options
    random.shuffle(options)
    return options


def prepare_quiz_data(
    test_words: List[Dict[str, str]], all_words: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Pre-generates options for all questions in the test list for session consistency."""
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


# --- Application Startup Event ---


@app.on_event("startup")
async def startup_event():
    """Load vocabulary data when the application starts."""
    global ALL_WORDS
    ALL_WORDS = load_words()


# --- Routes ---


@app.get("/", response_class=RedirectResponse)
async def start_quiz():
    """Initializes the quiz session and redirects to the first question."""
    if not ALL_WORDS:
        print("ERROR: Word database is empty.")
        # Correctly return an error response or redirect to an error page
        # For simplicity, we redirect to a non-quiz start state
        return HTMLResponse("<h1>Error: Word database is empty.</h1>", status_code=500)

    test_words = get_test_words()
    prepared_questions = prepare_quiz_data(test_words, ALL_WORDS)

    # Initialize a new quiz session state
    user_sessions[SESSION_ID] = {
        "prepared_questions": prepared_questions,
        "correct_count": 0,
        "total_questions": len(test_words),
        "answers": [],  # List of recorded answer dictionaries
    }

    return RedirectResponse(url="/quiz/0", status_code=302)


@app.get("/quiz/{index}", response_class=HTMLResponse)
async def display_question(
    request: Request,
    index: int,
):
    """
    Displays a specific question by index, showing the current state
    (answered or unanswered).
    """
    session_data = user_sessions.get(SESSION_ID)

    if not session_data:
        return RedirectResponse(url="/", status_code=302)

    total_questions = session_data["total_questions"]

    # Boundary check: If index is out of bounds, redirect to results page
    if index >= total_questions or index < 0:
        return RedirectResponse(url="/result", status_code=302)

    current_q_data = session_data["prepared_questions"][index]
    options = current_q_data["options"]

    # Check if this question has been answered
    answer_record = None
    if index < len(session_data["answers"]):
        answer_record = session_data["answers"][index]

    context = {
        "request": request,
        "word": current_q_data["word"],
        "options": options,
        "current_index": index,
        "total_questions": total_questions,
        "correct_translation": current_q_data[
            "translation"
        ],  # Crucial for feedback display in template
        "answer_record": answer_record,  # Pass record to template for display logic
        "is_first_question": index == 0,
        "is_last_question": index == total_questions - 1,
    }

    return templates.TemplateResponse("index.html", context)


@app.post("/submit_answer", response_class=JSONResponse)
async def submit_answer(
    word: str = Form(...), answer: str = Form(...), current_index: int = Form(...)
):
    """
    Processes the user's answer, records the result, and returns a JSON status
    for client-side feedback rendering.
    """
    session_data = user_sessions.get(SESSION_ID)

    if not session_data or current_index >= session_data["total_questions"]:
        return JSONResponse({"error": "Invalid session or index"}, status_code=400)

    # Prevent re-submission for an already recorded answer
    if current_index < len(session_data["answers"]):
        return JSONResponse(
            {"error": "Answer already recorded for this question."}, status_code=400
        )

    current_q_data = session_data["prepared_questions"][current_index]
    correct_translation = current_q_data["translation"]

    is_correct = answer == correct_translation

    if is_correct:
        session_data["correct_count"] += 1

    # Record the new answer
    record = {
        "word": word,
        "user_answer": answer,
        "correct_answer": correct_translation,
        "is_correct": is_correct,
        "attempted": True,  # Adding 'attempted' for clarity in the template (though not strictly necessary)
    }
    session_data["answers"].append(record)

    # Return the record data for client-side feedback
    return JSONResponse(record)


# --- Result Route ---


@app.get("/result", response_class=HTMLResponse)
async def show_result(request: Request):
    """Displays the final quiz result page."""
    session_data = user_sessions.get(SESSION_ID)

    if not session_data:
        # If no session, start a new quiz
        return RedirectResponse(url="/", status_code=302)

    correct_count = session_data["correct_count"]
    total_questions = session_data["total_questions"]

    # Check if all questions have been attempted
    if len(session_data["answers"]) < total_questions:
        # Optionally redirect back to the last unattempted question
        last_unanswered_index = len(session_data["answers"])
        return RedirectResponse(url=f"/quiz/{last_unanswered_index}", status_code=302)

    context = {
        "request": request,
        "correct_count": correct_count,
        "total_questions": total_questions,
        # Avoid potential division by zero if total_questions is 0 (though protected by initial checks)
        "score_percentage": (
            int((correct_count / total_questions) * 100) if total_questions else 0
        ),
        "answers": session_data["answers"],
    }

    return templates.TemplateResponse("result.html", context)


# --- Run Application ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
