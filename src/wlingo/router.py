import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Form,
    Request,
    Response,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .config import settings
from .globals import templates, vocab_manager
from .models import AnswerRecord, SessionData
from .quiz import QuizFactory
from .redis_session import redis_client

router = APIRouter()
logger = logging.getLogger("wlingo")


# --- Dependencies ---
def get_session_id(
    session_id: Optional[str] = Cookie(None, alias=settings.SESSION_COOKIE_NAME),
) -> Optional[str]:
    return session_id


def get_active_session(
    session_id: str = Depends(get_session_id),
) -> Optional[SessionData]:
    if not session_id:
        return None

    session_data = redis_client.get(session_id)
    if not session_data:
        return None

    session = SessionData.parse_raw(session_data)

    if datetime.now() - session.created_at > timedelta(
        minutes=settings.SESSION_TIMEOUT_MINUTES
    ):
        redis_client.delete(session_id)
        return None
    return session


# --- Routes ---
@router.get("/api/topics")
async def get_topics():
    return vocab_manager.get_topics()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("start.html", {"request": request})


@router.post("/start", response_class=RedirectResponse)
def start_quiz_session(
    request: Request,
    topic: str = Form(...),
):
    mode = "standard"
    if topic == "__arithmetic__":
        mode = "arithmetic"
        topic = "Arithmetic"

    if mode == "standard":
        # Validate topic exists
        if not vocab_manager.get_words(topic):
            topics = vocab_manager.get_topics()
            topic = topics[0]["id"] if topics else "default_dummy"
        generator = QuizFactory.create(mode, vocab_manager)
    else:  # mode is arithmetic
        generator = QuizFactory.create(mode)

    prepared_questions = generator.generate(topic, settings.TEST_SIZE)

    new_id = str(uuid.uuid4())
    session_data = SessionData(
        prepared_questions=prepared_questions,
        correct_count=0,
        total_questions=len(prepared_questions),
        answers=[],
        created_at=datetime.now(),
        topic=topic,
        mode=mode,
    )

    redis_client.set(
        new_id,
        session_data.model_dump_json(),
        ex=timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES),
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


@router.get("/api/quiz/{index}")
def get_question_data(
    index: int, session_data: SessionData = Depends(get_active_session)
):
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


@router.get("/quiz/{index}", response_class=HTMLResponse)
def display_question_page(
    request: Request,
    index: int,
    session_data: SessionData = Depends(get_active_session),
):
    if not session_data:
        return RedirectResponse(url="/", status_code=302)
    if index >= session_data.total_questions:
        return RedirectResponse(url="/result", status_code=302)
    return templates.TemplateResponse(
        "quiz.html",
        {
            "request": request,
            "current_index": index,
            "mode": session_data.mode,
            "topic": session_data.topic,
        },
    )


@router.post("/submit_answer", response_model=AnswerRecord)
def submit_answer(
    selected_option_index: int = Form(...),
    current_index: int = Form(...),
    session_id: str = Depends(get_session_id),
    session_data: SessionData = Depends(get_active_session),
):
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
    redis_client.set(
        session_id,
        session_data.model_dump_json(),
        ex=timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES),
    )
    return record


@router.get("/api/result")
def get_result_data(session_data: SessionData = Depends(get_active_session)):
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


@router.get("/result", response_class=HTMLResponse)
async def result_page(request: Request):
    return templates.TemplateResponse("result.html", {"request": request})


@router.post("/api/reset")
def reset_session(
    response: Response,
    session_id: str = Depends(get_session_id),
):
    if session_id:
        redis_client.delete(session_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}