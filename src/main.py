import logging
import os
import random
import uuid
import glob
from abc import ABC, abstractmethod
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


# --- Models ---
class Question(BaseModel):
    word: str
    translation: str
    options: List[str]


class SessionData(BaseModel):
    prepared_questions: List[Question]
    correct_count: int
    total_questions: int
    answers: List[Dict[str, Any]]
    created_at: datetime
    topic: str
    mode: str = "standard"  # New: Track quiz mode (standard, review, etc.)


class AnswerRecord(BaseModel):
    word: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    attempted: bool


# --- Configuration ---
class Settings:
    PROJECT_NAME: str = "wlingo"
    DEBUG: bool = False
    LOG_DIR: str = "log"
    LOG_FILE: str = "wlingo.log"
    VOCAB_DIR: str = "vocabulary"
    TEST_SIZE: int = 15
    SESSION_COOKIE_NAME: str = "quiz_session_id"
    SESSION_TIMEOUT_MINUTES: int = 120


settings = Settings()

# --- Logging Setup ---
if not os.path.exists(settings.LOG_DIR):
    os.makedirs(settings.LOG_DIR)
log_path = os.path.join(settings.LOG_DIR, settings.LOG_FILE)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(file_handler)

app = FastAPI(title=settings.PROJECT_NAME, debug=settings.DEBUG)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

sessions: Dict[str, SessionData] = {}


# --- Service Layer: Vocabulary Management ---
class VocabularyManager:
    """Manages loading and accessing vocabulary sets."""

    def __init__(self, directory: str):
        self.directory = directory
        self.vocab_sets: Dict[str, List[Dict[str, str]]] = {}
        self.load_all()

    def load_all(self):
        self.vocab_sets = {}
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)
            logger.warning(f"Created directory {self.directory}. Please add CSV files.")
            return

        csv_files = glob.glob(os.path.join(self.directory, "*.csv"))
        for file_path in csv_files:
            try:
                file_name = os.path.splitext(os.path.basename(file_path))[0]
                df = pd.read_csv(file_path, encoding="utf-8")
                if "word" in df.columns and "translation" in df.columns:
                    self.vocab_sets[file_name] = df.to_dict("records")
                    logger.info(f"Loaded {len(df)} words from {file_name}")
                else:
                    logger.error(f"Skipping {file_name}: Missing columns.")
            except Exception as e:
                logger.error(f"Failed to load {file_path}: {e}")

        if not self.vocab_sets:
            logger.warning("No CSV files found. Loading dummy data.")
            self.vocab_sets["default_dummy"] = [
                {"word": "Hund", "translation": "dog"},
                {"word": "Katze", "translation": "cat"},
                {"word": "Baum", "translation": "tree"},
                {"word": "Haus", "translation": "house"},
                {"word": "Wasser", "translation": "water"},
            ]

    def get_words(self, topic: str) -> List[Dict[str, str]]:
        return self.vocab_sets.get(topic, [])

    def get_topics(self) -> List[Dict[str, Any]]:
        topics = []
        for key, words in self.vocab_sets.items():
            display_name = key.replace("_", " ").title()
            topics.append({"id": key, "name": display_name, "count": len(words)})
        topics.sort(key=lambda x: x["name"])
        return topics


vocab_manager = VocabularyManager(settings.VOCAB_DIR)


# --- Strategy Pattern: Quiz Generators ---
class QuizGenerator(ABC):
    """Abstract Base Class for different quiz generation strategies."""

    @abstractmethod
    def generate(self, topic: str, count: int) -> List[Question]:
        pass

    def _generate_options(
        self, correct_translation: str, all_words: List[Dict[str, str]]
    ) -> List[str]:
        """Helper to generate random distractors."""
        all_translations = {w["translation"] for w in all_words}
        all_translations.discard(correct_translation)

        num_options = 3
        if len(all_translations) < num_options:
            incorrect = list(all_translations)
            while len(incorrect) < num_options:
                incorrect.append(f"Option {len(incorrect)+1}")
        else:
            incorrect = random.sample(list(all_translations), num_options)

        options = [correct_translation] + incorrect
        random.shuffle(options)
        return options


class RandomQuizGenerator(QuizGenerator):
    """Standard mode: Randomly selects N words from the topic."""

    def generate(self, topic: str, count: int) -> List[Question]:
        word_list = vocab_manager.get_words(topic)
        if not word_list:
            return []

        selected_words = random.sample(word_list, min(count, len(word_list)))

        return [
            Question(
                word=item["word"],
                translation=item["translation"],
                options=self._generate_options(item["translation"], word_list),
            )
            for item in selected_words
        ]


class QuizFactory:
    """Factory to select the appropriate generator."""

    @staticmethod
    def create(mode: str) -> QuizGenerator:
        # In the future, you can add "review", "hard", "ai_generated" modes here
        if mode == "standard":
            return RandomQuizGenerator()
        else:
            # Fallback
            return RandomQuizGenerator()


# --- Dependencies ---
def get_session_id(
    session_id: Optional[str] = Cookie(None, alias=settings.SESSION_COOKIE_NAME)
) -> Optional[str]:
    return session_id


def get_active_session(session_id: str) -> Optional[SessionData]:
    if not session_id or session_id not in sessions:
        return None
    session = sessions[session_id]
    if datetime.now() - session.created_at > timedelta(
        minutes=settings.SESSION_TIMEOUT_MINUTES
    ):
        del sessions[session_id]
        return None
    return session


# --- Lifecycle ---
@app.on_event("startup")
async def startup_event():
    # Reloads vocab on startup (manager handles logic)
    vocab_manager.load_all()


# --- Routes ---


@app.get("/api/topics")
async def get_topics():
    return vocab_manager.get_topics()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("start.html", {"request": request})


@app.post("/start", response_class=RedirectResponse)
async def start_quiz_session(
    response: Response,
    topic: str = Form(...),
    mode: str = Form("standard"),  # Allow mode selection in future
):
    # Validate topic exists
    if not vocab_manager.get_words(topic):
        # Fallback to first available
        topics = vocab_manager.get_topics()
        topic = topics[0]["id"] if topics else "default_dummy"

    # --- Use Factory to generate questions ---
    generator = QuizFactory.create(mode)
    prepared_questions = generator.generate(topic, settings.TEST_SIZE)

    new_id = str(uuid.uuid4())
    sessions[new_id] = SessionData(
        prepared_questions=prepared_questions,
        correct_count=0,
        total_questions=len(prepared_questions),
        answers=[],
        created_at=datetime.now(),
        topic=topic,
        mode=mode,
    )

    logger.info(f"New session: {new_id} [Topic: {topic}, Mode: {mode}]")

    redirect = RedirectResponse(url="/quiz/0", status_code=302)
    redirect.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=new_id,
        httponly=True,
        samesite="Lax",
    )
    return redirect


@app.get("/api/quiz/{index}")
async def get_question_data(index: int, session_id: str = Depends(get_session_id)):
    session_data = get_active_session(session_id)
    if not session_data:
        return JSONResponse({"error": "Session invalid"}, status_code=401)
    if not (0 <= index < session_data.total_questions):
        return JSONResponse({"error": "Index error"}, status_code=404)

    current_q = session_data.prepared_questions[index]
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
    selected_option_index: int = Form(...),
    current_index: int = Form(...),
    session_id: str = Depends(get_session_id),
):
    session_data = get_active_session(session_id)
    if not session_data or not (0 <= current_index < session_data.total_questions):
        return JSONResponse({"error": "Invalid session"}, status_code=401)
    if current_index < len(session_data.answers):
        return JSONResponse({"error": "Already answered"}, status_code=400)

    current_q = session_data.prepared_questions[current_index]
    if not (0 <= selected_option_index < len(current_q.options)):
        return JSONResponse({"error": "Invalid option"}, status_code=400)

    user_answer_str = current_q.options[selected_option_index]
    is_correct = user_answer_str == current_q.translation

    if is_correct:
        session_data.correct_count += 1

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
    session_data = get_active_session(session_id)
    if not session_data:
        return JSONResponse({"error": "Session invalid"}, status_code=401)

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
    return templates.TemplateResponse("result.html", {"request": request})


@app.post("/api/reset")
async def reset_session(response: Response, session_id: str = Depends(get_session_id)):
    if session_id in sessions:
        del sessions[session_id]
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
