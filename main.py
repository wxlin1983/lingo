import pandas as pd
import random
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Optional
from urllib.parse import quote

# --- Configuration ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
WORDS_FILE = "words.csv"
TEST_SIZE = 15

# Global storage (simulate a database)
ALL_WORDS: List[Dict[str, str]] = []
user_sessions: Dict[str, Dict] = {}
SESSION_ID = "test_session"


# --- Core Logic Functions ---


def load_words() -> List[Dict[str, str]]:
    """Loads the word list from the CSV file."""
    try:
        # Assuming words.csv has 'word' and 'translation' columns
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
    incorrect_translations = [
        w["translation"] for w in all_words if w["translation"] != correct_translation
    ]

    # Ensure we get 3 unique wrong options if possible
    wrong_options = random.sample(
        incorrect_translations, min(3, len(incorrect_translations))
    )

    # Pad if we have fewer than 3 incorrect options (unlikely in a large list)
    while len(wrong_options) < 3:
        # Just repeat an existing wrong option or a dummy if needed
        wrong_options.append(
            random.choice(incorrect_translations)
            if incorrect_translations
            else "Placeholder"
        )

    options = [correct_translation] + wrong_options
    random.shuffle(options)
    return options


# --- Application Startup Event ---


@app.on_event("startup")
async def startup_event():
    global ALL_WORDS
    ALL_WORDS = load_words()
    if not ALL_WORDS:
        print("WARNING: Word database is empty or failed to load!")


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def start_quiz(request: Request):
    """Initializes the quiz and redirects to the first question."""
    if not ALL_WORDS:
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
async def display_question(
    request: Request,
    index: int,
    # Query parameters for feedback (only used for incorrect answers)
    feedback: Optional[str] = None,
    user_ans: Optional[str] = None,
    correct_ans: Optional[str] = None,
):
    """
    Displays a specific question by index, optionally showing feedback
    if redirected from an incorrect submission.
    """
    session_data = user_sessions.get(SESSION_ID)

    if not session_data or index >= session_data["total_questions"]:
        # If index is out of bounds, check if quiz is finished
        if session_data and index == session_data["total_questions"]:
            return RedirectResponse(url="/result", status_code=302)
        return RedirectResponse(url="/", status_code=302)

    current_word_data = session_data["test_words"][index]

    # If feedback is provided, it means the user was incorrect and we are showing the review screen.
    if feedback is not None and feedback == "incorrect":
        context = {
            "request": request,
            "word": current_word_data["word"],
            "current_index": index,
            "total_questions": session_data["total_questions"],
            # Feedback data
            "feedback": feedback,
            "user_answer": user_ans,
            "correct_answer": correct_ans,
            "options": [],  # Hide options during feedback
        }
        return templates.TemplateResponse("index.html", context)

    # --- Standard Question Display (If not in feedback mode) ---

    # If already answered, redirect to the next unanswered question or result
    if index < len(session_data["answers"]):
        next_index = len(session_data["answers"])
        if next_index < session_data["total_questions"]:
            return RedirectResponse(url=f"/quiz/{next_index}", status_code=302)
        else:
            return RedirectResponse(url="/result", status_code=302)

    options = generate_options(current_word_data["translation"], ALL_WORDS)

    context = {
        "request": request,
        "word": current_word_data["word"],
        "options": options,
        "current_index": index,
        "total_questions": session_data["total_questions"],
        "feedback": None,  # Ensure feedback is None for normal question view
    }
    return templates.TemplateResponse("index.html", context)


@app.post("/submit_answer", response_class=RedirectResponse)
async def submit_answer(
    word: str = Form(...), answer: str = Form(...), current_index: int = Form(...)
):
    """
    Processes the user's answer.
    If correct: redirects to the next question/result.
    If incorrect: redirects back to the current question with feedback.
    """
    session_data = user_sessions.get(SESSION_ID)

    if not session_data or current_index >= session_data["total_questions"]:
        return RedirectResponse(url="/", status_code=302)

    current_word_data = session_data["test_words"][current_index]
    correct_translation = current_word_data["translation"]

    is_correct = answer == correct_translation

    # Store the answer record (only if it hasn't been recorded yet)
    if current_index >= len(session_data["answers"]):
        if is_correct:
            session_data["correct_count"] += 1

        session_data["answers"].append(
            {
                "word": word,
                "user_answer": answer,
                "correct_answer": correct_translation,
                "is_correct": is_correct,
            }
        )

    next_index = current_index + 1

    if is_correct:
        # If correct: Redirect directly to the next question or result
        if next_index >= session_data["total_questions"]:
            return RedirectResponse(url="/result", status_code=303)
        else:
            return RedirectResponse(url=f"/quiz/{next_index}", status_code=303)
    else:
        # If incorrect: Redirect back to the current question with URL-encoded feedback
        feedback_type = "incorrect"

        return RedirectResponse(
            url=(
                f"/quiz/{current_index}?"
                f"feedback={feedback_type}&"
                f"user_ans={quote(answer)}&"
                f"correct_ans={quote(correct_translation)}"
            ),
            status_code=303,  # 303 See Other is best for POST-redirect-GET pattern
        )


# --- Result Route ---


@app.get("/result", response_class=HTMLResponse)
async def show_result(request: Request):
    """Displays the quiz result page."""
    session_data = user_sessions.get(SESSION_ID)

    if (
        not session_data
        or len(session_data["answers"]) < session_data["total_questions"]
    ):
        # Redirect to start if the quiz wasn't finished
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

    # You would typically need a words.csv file in the same directory
    # with 'word' and 'translation' columns to run this successfully.
    # Example:
    # word,translation
    # Hund,dog
    # Katze,cat

    uvicorn.run(app, host="0.0.0.0", port=8000)
