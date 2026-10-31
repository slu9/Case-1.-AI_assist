"""Цикл агента с подтверждением человека и журнал действий (task.md §10.8)."""
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .llm import LLM, LLMError, ToolCall
from .tools import Backend, BackendError, Context, dictionaries_context, Draft, Tool, TOOLS


DEFAULT_PATH = Path(os.environ.get("CAMPAIGN_LOG_PATH", Path(__file__).resolve().parents[1] / "logs" / "agent_actions.jsonl"))


# --- Журнал действий ---


class Journal:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)

    def write(self, session_id: str, user: str, role: str, event: str, **details) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat(),
            "session": session_id,
            "user": user,
            "role": role,
            "event": event,
            **details,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")


MAX_STEPS = 25
MAX_TURN_FAILURES = 6
MAX_SAME_FAILURES = 3  # модель не должна тратить квоту, повторяя одну и ту же ошибку
EDITABLE_FIELDS = {"create_tag": ("name",), "create_place": ("code", "description")}
SYSTEM_PROMPT = (Path(__file__).parent / "system.md").read_text(encoding="utf-8")
TOOL_DEFINITIONS = [tool.definition() for tool in TOOLS.values()]
READ_ONLY_DEFINITIONS = [t.definition() for t in TOOLS.values() if not t.write and not t.name.startswith("draft_")]


@dataclass
class Pending:
    """Ход модели, ожидающий решения: на каждый tool_use нужен результат в одном сообщении."""
    ready: dict[str, dict]  # id вызова -> готовый результат
    calls: list[ToolCall]  # все вызовы хода, в исходном порядке
    gated: list[ToolCall]  # те, что ждут подтверждения


# --- Цикл агента ---


@dataclass
class Session:
    user: str
    role: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[dict] = field(default_factory=list)
    draft: Draft = field(default_factory=Draft)
    pending: Pending | None = None
    on_tool: Callable[[str], None] | None = None  # интерфейс показывает ход работы


@dataclass
class Turn:
    text: str
    confirmation: list[dict] | None = None  # что показать человеку на подтверждение
    error: str | None = None


def result(call: ToolCall, content, is_error: bool = False) -> dict:
    return {"id": call.id, "name": call.name, "content": content, "is_error": is_error}


def available_tools(session: Session) -> list[dict]:
    """На вопрос агент отвечает: менять он может только в ответ на просьбу."""
    said = [m["text"] for m in session.messages if m["role"] == "user"]
    if said and said[-1].rstrip().endswith("?"):
        return READ_ONLY_DEFINITIONS
    return TOOL_DEFINITIONS


def failure_reason(results: list[dict]) -> str:
    for item in results:
        content = item["content"] if isinstance(item["content"], dict) else {}
        if content.get("errors"):
            return content["errors"][0]["message"]
        if content.get("reason"):
            return content["reason"]
    return "модель не смогла исправить данные"


class Agent:
    def __init__(self, llm: LLM, backend: Backend, journal: Journal | None = None):
        self.llm = llm
        self.backend = backend
        self.journal = journal or Journal()

    def send(self, session: Session, text: str) -> Turn:
        if session.pending:
            # Новое сообщение вместо решения значит, что действие не подтверждено.
            message = self._decided(session, approved=False, note="Пользователь не подтвердил и написал новое сообщение")
            message["text"] = text
            session.messages.append(message)
        else:
            session.messages.append({"role": "user", "text": text})
        return self._run(session)

    def decide(self, session: Session, approved: bool, comment: str | None = None, edits: dict | None = None) -> Turn:
        if session.pending is None:
            return Turn("", error="Нет действий, ожидающих подтверждения")
        for call in session.pending.gated:  # поля формы новой записи справочника (task.md §10.4)
            allowed = EDITABLE_FIELDS.get(call.name, ())
            call.input.update({key: value for key, value in (edits or {}).items() if key in allowed})
        note = f"Пользователь отклонил действие. {comment or ''}".strip()
        session.messages.append(self._decided(session, approved, note))
        return self._run(session)

    def _context(self, session: Session) -> Context:
        said = [m["text"] for m in session.messages if m["role"] == "user"]
        return Context(self.backend, session.user, session.role, session.draft, " ".join(said), said[-1] if said else "")

    def _log(self, session: Session, event: str, **details) -> None:
        self.journal.write(session.id, session.user, session.role, event, **details)

    def _execute(self, session: Session, tool: Tool, call: ToolCall) -> dict:
        if session.on_tool:
            session.on_tool(call.name)
        try:
            content = tool.run(self._context(session), call.input)
        except BackendError as exc:
            self._log(session, "tool_call", tool=call.name, input=call.input, ok=False, errors=exc.errors)
            return result(call, {"ok": False, "errors": exc.errors}, is_error=True)
        self._log(session, "tool_call", tool=call.name, input=call.input, ok=True)
        return result(call, content)

    def _decided(self, session: Session, approved: bool, note: str) -> dict:
        pending, session.pending = session.pending, None
        results = dict(pending.ready)
        names = [call.name for call in pending.gated]
        self._log(session, "approved" if approved else "rejected", tools=names, note=None if approved else note)

        failed = False
        for call in pending.gated:
            if not approved:
                results[call.id] = result(call, {"ok": False, "reason": note}, is_error=True)
            elif failed:
                reason = "Не выполнено: предыдущее действие завершилось ошибкой"
                results[call.id] = result(call, {"ok": False, "reason": reason}, is_error=True)
            else:
                results[call.id] = self._execute(session, TOOLS[call.name], call)
                failed = results[call.id]["is_error"]
        return {"role": "tool", "results": [results[call.id] for call in pending.calls]}

    def _process_calls(self, session: Session, calls: list[ToolCall]) -> Pending:
        ready, gated = {}, []
        for call in calls:
            tool = TOOLS.get(call.name)
            if tool is None:
                ready[call.id] = result(call, {"ok": False, "reason": "Нет такого инструмента"}, is_error=True)
            elif missing := [key for key in tool.schema.get("required", []) if key not in call.input]:
                # Схемы не строгие: без этой проверки инструмент упал бы на подстановке id в путь.
                self._log(session, "tool_call", tool=call.name, input=call.input, ok=False, missing=missing)
                ready[call.id] = result(call, {"ok": False, "reason": f"Не хватает полей: {', '.join(missing)}"}, is_error=True)
            elif not tool.write:
                ready[call.id] = self._execute(session, tool, call)
            else:
                errors = self._precheck(session, tool, call)
                if errors:
                    self._log(session, "precheck_failed", tool=call.name, input=call.input, errors=errors)
                    ready[call.id] = result(call, {"ok": False, "errors": errors}, is_error=True)
                else:
                    gated.append(call)
        return Pending(ready, calls, gated)

    def _precheck(self, session: Session, tool: Tool, call: ToolCall) -> list[dict]:
        if tool.precheck is None:
            return []
        try:
            return tool.precheck(self._context(session), call.input)
        except BackendError as exc:
            return exc.errors

    def _confirmation(self, session: Session, gated: list[ToolCall]) -> list[dict]:
        return [
            {
                "tool": call.name,
                "title": TOOLS[call.name].description,
                "input": session.draft.snapshot() if call.name == "apply_draft" else call.input,
            }
            for call in gated
        ]

    def _run(self, session: Session) -> Turn:
        try:
            dictionaries = dictionaries_context(self._context(session).dictionaries())
        except BackendError:
            return Turn("", error="Сервис кампаний недоступен")
        context = (
            f"Сегодня {date.today().isoformat()}. Пользователь: {session.user}, роль: {session.role}.\n\n{dictionaries}"
        )
        texts = []
        failures = total_failures = 0
        for _ in range(MAX_STEPS):
            try:
                response = self.llm.complete(SYSTEM_PROMPT, context, session.messages, available_tools(session))
            except LLMError as exc:
                return Turn("\n\n".join(texts), error=str(exc))

            self._log(session, "llm_call", model=response.model, stop_reason=response.stop_reason)
            if response.stop_reason == "refusal":
                # Ответ-отказ в историю не идёт, иначе следующий запрос повторит его контекст.
                return Turn("\n\n".join(texts), error="Модель отказалась отвечать на этот запрос")
            session.messages.append({
                "role": "assistant", "text": response.text, "tool_calls": response.tool_calls, "raw": response.raw,
            })
            if response.text:
                texts.append(response.text)
            if response.stop_reason == "max_tokens":
                return Turn("\n\n".join(texts), error="Ответ модели оборвался на лимите длины")
            if not response.tool_calls:
                return Turn("\n\n".join(texts))

            pending = self._process_calls(session, response.tool_calls)
            if pending.gated:
                session.pending = pending
                return Turn("\n\n".join(texts), confirmation=self._confirmation(session, pending.gated))
            results = [pending.ready[call.id] for call in pending.calls]
            session.messages.append({"role": "tool", "results": results})
            failed = any(r["is_error"] for r in results)
            failures = failures + 1 if failed else 0
            total_failures += failed
            if failures >= MAX_SAME_FAILURES or total_failures >= MAX_TURN_FAILURES:
                return Turn("\n\n".join(texts), error=f"Не получилось: {failure_reason(results)}. Уточните запрос.")

        return Turn("\n\n".join(texts), error="Превышено число шагов агента за один ход")
