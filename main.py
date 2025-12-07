import pandas as pd
import random
import json
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Optional, Any
from urllib.parse import quote

# --- Configuration ---
app = FastAPI()
# NOTE: Ensure you have a 'templates' directory with 'index.html' and 'result.html'
templates = Jinja2Templates(directory="templates")
WORDS_FILE = "words.csv"
TEST_SIZE = 15

# Global storage (simulate a database)
ALL_WORDS: List[Dict[str, str]] = []
# Session storage keys the session ID to the user's quiz state
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
        print(f"ERROR: File {WORDS_FILE} not found. Please create one.")
        # Create a dummy file for the app to run without erroring out immediately
        # You should replace this with a real file.
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
    if len(ALL_WORDS) < TEST_SIZE:
        return random.sample(ALL_WORDS, len(ALL_WORDS))
    return random.sample(ALL_WORDS, TEST_SIZE)


def generate_options(
    correct_translation: str, all_words: List[Dict[str, str]]
) -> List[str]:
    """Generates four options (one correct, three wrong) for a given translation."""
    if not all_words:
        return [correct_translation]

    incorrect_translations = [
        w["translation"] for w in all_words if w["translation"] != correct_translation
    ]

    wrong_options = random.sample(
        incorrect_translations, min(3, len(incorrect_translations))
    )
    # Pad if we have fewer than 3 incorrect options (unlikely in a large list)
    while len(wrong_options) < 3:
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


# --- Routes ---


@app.get("/", response_class=RedirectResponse)
async def start_quiz():
    """Initializes the quiz and redirects to the first question."""
    if not ALL_WORDS:
        # In a real app, this would redirect to a proper error page
        print("ERROR: Word database is empty.")
        return RedirectResponse(url="/", status_code=500)

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
    # Query parameter for feedback data (JSON string)
    feedback_data: Optional[str] = None,
):
    """
    Displays a specific question by index, or displays feedback if provided.
    """
    session_data = user_sessions.get(SESSION_ID)

    if not session_data:
        return RedirectResponse(url="/", status_code=302)

    # Check if quiz is finished
    if index >= session_data["total_questions"]:
        return RedirectResponse(url="/result", status_code=302)

    current_word_data = session_data["test_words"][index]

    # --- Feedback Mode (After an incorrect submission) ---
    if feedback_data:
        try:
            feedback = json.loads(feedback_data)
        except json.JSONDecodeError:
            feedback = {
                "is_correct": False,
                "user_answer": "Error",
                "correct_answer": "Error",
            }

        context = {
            "request": request,
            "word": current_word_data["word"],
            "current_index": index,
            "total_questions": session_data["total_questions"],
            "feedback": feedback,
            "options": [],  # Hide options during feedback
        }
        return templates.TemplateResponse("index.html", context)

    # --- Standard Question Display ---

    # If the question was already answered correctly, skip it (incorrect ones require review)
    # The length of 'answers' tells us how many questions have been *submitted*
    if (
        index < len(session_data["answers"])
        and session_data["answers"][index]["is_correct"]
    ):
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
        "feedback": None,
    }
    return templates.TemplateResponse("index.html", context)


@app.post("/submit_answer", response_class=JSONResponse)
async def submit_answer(
    word: str = Form(...), answer: str = Form(...), current_index: int = Form(...)
):
    """
    Processes the user's answer, records it, and returns a JSON response.
    This route handles NO REDIRECTION.
    """
    session_data = user_sessions.get(SESSION_ID)

    if not session_data or current_index >= session_data["total_questions"]:
        return JSONResponse({"error": "Invalid session or index"}, status_code=400)

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

    # Return data for the client (JavaScript) to handle redirection/feedback display
    return JSONResponse(
        {
            "is_correct": is_correct,
            "current_index": current_index,
            "next_index": current_index + 1,
            "total_questions": session_data["total_questions"],
            "user_answer": answer,
            "correct_answer": correct_translation,
        }
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

    # NOTE: This requires a 'result.html' template to exist in the 'templates' directory
    return templates.TemplateResponse("result.html", context)


# --- Run Application ---
if __name__ == "__main__":
    import uvicorn

    # To run this, you need a 'words.csv' file and the Jinja2 templates.
    uvicorn.run(app, host="0.0.0.0", port=8000)
