"""HTTP-сервис ассистента для интерфейса.

Запуск: uvicorn --factory backend.server:create_app --port 8001
Сообщение возвращается потоком NDJSON: статусы работы, затем итог хода и состояние сессии.
Сессии живут в памяти процесса.
"""
import hashlib
import json
import os
import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .agent import Agent, Session, Turn
from .llm import GigaChatLLM, LLMError
from .tools import Backend, BackendError, Context


STATUS_BY_TOOL = {
    "get_topics": "Анализирую бриф",
    "get_tags": "Анализирую бриф",
    "get_segments": "Подбираю аудиторию",
    "get_segment_types": "Подбираю аудиторию",
    "draft_set_segments": "Подбираю аудиторию",
    "get_places": "Проверяю места показа",
    "get_banner_types": "Собираю креативы",
    "get_channels": "Собираю креативы",
    "draft_upsert_banner": "Собираю креативы",
    "draft_upsert_content": "Собираю креативы",
    "draft_set_creatives": "Собираю креативы",
    "draft_review": "Проверяю ограничения",
    "apply_draft": "Сохраняю кампанию",
}
DEFAULT_STATUS = "Обновляю кампанию"


class NewSession(BaseModel):
    user: str = "ivanov.p"
    role: str = "campaignManager"


class Message(BaseModel):
    text: str


IMAGE_PAUSE_SECONDS = 60


class Decision(BaseModel):
    approved: bool
    comment: str | None = None
    edits: dict[str, str] | None = None


def progress(session: Session, review: dict) -> dict:
    """Готовность считается по тем же данным, что и проверка: что заполнено, а чего не хватает."""
    draft = session.draft
    campaign = draft.campaign
    audience = campaign.get("audienceType")
    has_audience = audience == "ALL_USERS" or bool(draft.included)
    checks = [
        ("Название", bool(campaign.get("name"))),
        ("Тематика", bool(campaign.get("topic"))),
        ("Дата и время начала", bool(campaign.get("startDate") and campaign.get("startTime"))),
        ("Окончание показа", "endDate" in campaign),
        ("Аудитория", has_audience),
        ("Места показа", bool(campaign.get("places"))),
        ("Баннер", bool(draft.banners)),
        ("Креативы", bool(draft.creatives)),
    ]
    done = sum(ok for _, ok in checks)
    return {
        "percent": round(100 * done / len(checks)),
        "missing": [name for name, ok in checks if not ok],
        "ready": review["ready"],
    }


def state_of(agent: Agent, session: Session) -> dict:
    ctx = Context(agent.backend, session.user, session.role, session.draft)
    review = session.draft.review(ctx.dictionaries())
    return {
        "id": session.id,
        "user": session.user,
        "role": session.role,
        "draft": session.draft.snapshot(),
        "review": review,
        "progress": progress(session, review),
        "awaitingConfirmation": session.pending is not None,
    }


def turn_of(turn: Turn) -> dict:
    return {"text": turn.text, "confirmation": turn.confirmation, "error": turn.error}


def stream(agent: Agent, session: Session, run: Callable[[], Turn]) -> Iterator[str]:
    """Агент работает в потоке, а статусы инструментов сразу уходят клиенту."""
    events: queue.Queue = queue.Queue()

    def on_tool(name: str) -> None:
        events.put({"type": "status", "label": STATUS_BY_TOOL.get(name, DEFAULT_STATUS)})

    def worker() -> None:
        session.on_tool = on_tool
        try:
            turn = run()
            events.put({"type": "turn", "turn": turn_of(turn), "session": state_of(agent, session)})
        except (BackendError, LLMError, OSError) as exc:
            events.put({"type": "turn", "turn": {"text": "", "confirmation": None, "error": str(exc)}})
        finally:
            session.on_tool = None
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    for event in iter(events.get, None):
        yield json.dumps(event, ensure_ascii=False) + "\n"


def create_app(agent: Agent | None = None, images: Path | None = None) -> FastAPI:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    images = images or Path(os.environ.get("CAMPAIGN_IMAGE_DIR", root / "images"))
    drawing = threading.Lock()  # GigaChat рисует по одному запросу, остальные ждут очереди
    paused_until = [0.0]  # после сбоя не повторяем запрос: иначе каждая обложка продлевает лимит
    agent = agent or Agent(GigaChatLLM(), Backend())
    sessions: dict[str, Session] = {}
    app = FastAPI(title="Campaign Assistant Agent")

    def get(session_id: str) -> Session:
        if session_id not in sessions:
            raise HTTPException(404, "Диалог не найден")
        return sessions[session_id]

    @app.post("/sessions", status_code=201)
    def create_session(body: NewSession):
        session = Session(body.user, body.role)
        sessions[session.id] = session
        return state_of(agent, session)

    @app.get("/sessions/{session_id}")
    def read_session(session_id: str):
        return state_of(agent, get(session_id))

    @app.post("/sessions/{session_id}/messages")
    def send(session_id: str, body: Message):
        session = get(session_id)
        return StreamingResponse(
            stream(agent, session, lambda: agent.send(session, body.text)), media_type="application/x-ndjson",
        )

    @app.post("/sessions/{session_id}/decision")
    def decide(session_id: str, body: Decision):
        session = get(session_id)
        return StreamingResponse(
            stream(agent, session, lambda: agent.decide(session, body.approved, body.comment, body.edits)),
            media_type="application/x-ndjson",
        )

    @app.get("/image")
    def image(brief: str = Query(min_length=1, max_length=400)):
        """Картинка рисуется один раз на текст креатива и дальше берётся с диска."""
        path = images / f"{hashlib.sha256(brief.encode()).hexdigest()[:20]}.jpg"
        if not path.exists():  # готовая картинка не ждёт очереди генерации
            with drawing:
                if not path.exists():
                    if time.monotonic() < paused_until[0]:
                        raise HTTPException(503, "Генерация изображений приостановлена")
                    try:
                        picture = agent.llm.draw(brief)
                    except LLMError as exc:
                        paused_until[0] = time.monotonic() + IMAGE_PAUSE_SECONDS
                        raise HTTPException(502, str(exc)) from exc
                    images.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(picture)
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    return app
