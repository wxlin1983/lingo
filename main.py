import pandas as pd
import random
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict

# --- Configuration ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
WORDS_FILE = "words.csv"
TEST_SIZE = 15  # Number of words per quiz

# Global storage for word data
ALL_WORDS: List[Dict[str, str]] = []

# Temporary session storage (in-memory for this example)
user_sessions: Dict[str, Dict] = {}
SESSION_ID = "test_session"  # Simplified session ID

# --- Core Logic Functions ---


def load_words() -> List[Dict[str, str]]:
    """Loads the word list from the CSV file."""
    try:
        df = pd.read_csv(WORDS_FILE, encoding="utf-8")
        return df.to_dict("records")
    except FileNotFoundError:
        print(f"ERROR: File {WORDS_FILE} not found.")
        return []


def get_test_words() -> List[Dict[str, str]]:
    """Randomly selects TEST_SIZE words for the quiz."""
    if len(ALL_WORDS) < TEST_SIZE:
        return random.sample(ALL_WORDS, len(ALL_WORDS))
    return random.sample(ALL_WORDS, TEST_SIZE)


def generate_options(
    correct_translation: str, all_words: List[Dict[str, str]]
) -> List[str]:
    """Generates four options (one correct, three wrong) for a given translation."""
    # Get all possible incorrect translations
    incorrect_translations = [
        w["translation"] for w in all_words if w["translation"] != correct_translation
    ]

    # Select up to 3 random wrong options
    if len(incorrect_translations) >= 3:
        wrong_options = random.sample(incorrect_translations, 3)
    else:
        # Fallback if insufficient unique wrong options
        wrong_options = incorrect_translations + random.choices(
            incorrect_translations, k=3 - len(incorrect_translations)
        )

    options = [correct_translation] + wrong_options
    random.shuffle(options)
    return options


# --- Application Startup Event ---


@app.on_event("startup")
async def startup_event():
    """Loads word data when the application starts."""
    global ALL_WORDS
    ALL_WORDS = load_words()
    if not ALL_WORDS:
        print("WARNING: Word database is empty or failed to load!")


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def start_quiz(request: Request):
    """Initializes the quiz and redirects to the first question."""
    if not ALL_WORDS:
        # Render the error message in the index template
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Word database failed to load or is empty."},
            status_code=500,
        )

    test_words = get_test_words()

    # Initialize a new quiz session
    user_sessions[SESSION_ID] = {
        "test_words": test_words,
        "current_index": 0,
        "correct_count": 0,
        "total_questions": len(test_words),
        "answers": [],
    }

    return RedirectResponse(url="/quiz/0", status_code=302)


@app.get("/quiz/{index}", response_class=HTMLResponse)
async def display_question(request: Request, index: int):
    """Displays a specific question by index."""
    session_data = user_sessions.get(SESSION_ID)

    if not session_data or index >= session_data["total_questions"]:
        # Quiz finished or invalid index
        return RedirectResponse(url="/result", status_code=302)

    current_word_data = session_data["test_words"][index]

    # Check if already answered
    if index < len(session_data["answers"]):
        return RedirectResponse(url=f"/quiz/{index+1}", status_code=302)

    # Generate options
    options = generate_options(current_word_data["translation"], ALL_WORDS)

    context = {
        "request": request,
        "word": current_word_data["word"],
        "options": options,
        "current_index": index,
        "total_questions": session_data["total_questions"],
    }
    return templates.TemplateResponse("index.html", context)


@app.post("/submit_answer", response_class=RedirectResponse)
async def submit_answer(
    word: str = Form(...), answer: str = Form(...), current_index: int = Form(...)
):
    """Processes the user's answer and directs to the next question or result page."""
    session_data = user_sessions.get(SESSION_ID)

    if not session_data:
        return RedirectResponse(url="/", status_code=302)

    current_word_data = session_data["test_words"][current_index]
    correct_translation = current_word_data["translation"]

    is_correct = answer == correct_translation
    if is_correct:
        session_data["correct_count"] += 1

    # Store the answer record
    session_data["answers"].append(
        {
            "word": word,
            "user_answer": answer,
            "correct_answer": correct_translation,
            "is_correct": is_correct,
        }
    )

    next_index = current_index + 1

    if next_index < session_data["total_questions"]:
        # Move to the next question
        return RedirectResponse(url=f"/quiz/{next_index}", status_code=302)
    else:
        # Quiz finished
        return RedirectResponse(url="/result", status_code=302)


# --- Result Route ---


@app.get("/result", response_class=HTMLResponse)
async def show_result(request: Request):
    """Displays the quiz result page."""
    session_data = user_sessions.get(SESSION_ID)

    if (
        not session_data
        or len(session_data["answers"]) < session_data["total_questions"]
    ):
        # Redirect to start if quiz is incomplete
        return RedirectResponse(url="/", status_code=302)

    correct_count = session_data["correct_count"]
    total_questions = session_data["total_questions"]

    context = {
        "request": request,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "score_percentage": int((correct_count / total_questions) * 100),
        "answers": session_data["answers"],
    }

    return templates.TemplateResponse("result.html", context)


# --- Run Application ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
