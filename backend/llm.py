"""Слой LLM: логика агента не знает про конкретного провайдера (task.md §10.8).

История хранится в нейтральном виде. Сообщение ассистента дополнительно несёт `raw`:
ответ провайдера как есть, чтобы вернуть его в следующий запрос без изменений.

Адаптер GigaChat. Ключ и область SDK читает сам: GIGACHAT_CREDENTIALS, GIGACHAT_SCOPE.
Серверы подписаны российским корневым сертификатом, он лежит в certs и действует только
для этого клиента. Схемы инструментов упрощаются: GigaChat принимает только плоский
JSON Schema, а полная проверка всё равно идёт через Pydantic на входе в инструмент.
"""
import base64
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from gigachat import GigaChat
from gigachat.exceptions import AuthenticationError, GigaChatException, RateLimitError
from gigachat.models import Chat, Function, Messages, MessagesRole


DEFAULT_MODEL = "GigaChat-3-Ultra"
ROOT_CERTIFICATE = Path(__file__).resolve().parents[1] / "certs" / "russian_trusted_root_ca.pem"
MAX_TOKENS = 2000
RETRY_DELAYS = (3, 10, 20)
REPETITION_PENALTY = 1.1  # без него модель иногда повторяет одну фразу до лимита токенов
TEMPERATURE = 0.2  # при значении по умолчанию модель на повторах раздувает тексты
REQUEST_TIMEOUT_SECONDS = 120
SUBJECT_PROMPT = (
    "Реклама: {brief}\nНазови один простой физический предмет, не человека, который сразу передаёт тему этой рекламы: "
    "автомобиль, чемодан, чашка кофе, подарочная коробка. Ответь только названием предмета, 1-3 слова."
)
IMAGE_PROMPT = (
    "Нарисуй минималистичную 3D-иконку: {subject}. Один объект целиком по центру, узнаваемый силуэт, глянцевый пластик "
    "и матовое стекло, мягкие скруглённые формы, мягкий студийный свет, стиль современного приложения. "
    "Без людей, лиц и частей тела. Цвета объекта: лаймовый, зелёный, мятный и белый. Фон однотонный или плавный градиент от светло-лаймового "
    "к мятному, пустой, без окружения. Не фотография. Без текста, букв, цифр и логотипов."
)
KEPT_FIELDS = ("type", "description", "enum")


# --- Контракт модели ---


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn, tool_use, max_tokens, refusal
    raw: Any = None
    model: str | None = None


class LLM(Protocol):
    def complete(self, system: str, context: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """system неизменен между запросами, context меняется (например, дата)."""


# --- Схемы для GigaChat ---


def plain_schema(schema: dict, definitions: dict | None = None) -> dict:
    """Разворачивает $ref и anyOf; объединение объектов становится одним объектом со всеми полями."""
    definitions = {**(definitions or {}), **schema.get("$defs", {})}
    if "$ref" in schema:
        return plain_schema(definitions[schema["$ref"].rsplit("/", 1)[-1]], definitions)

    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        real = [variant for variant in variants if variant.get("type") != "null"]
        if len(real) == 1:
            inner, outer = plain_schema(real[0], definitions), _kept(schema)
            description = " ".join(filter(None, (outer.get("description"), inner.get("description"))))
            return {**inner, **outer, **({"description": description} if description else {})}
        return {**_merged([plain_schema(variant, definitions) for variant in real]), **_kept(schema)}

    result = _kept(schema)
    if "const" in schema:
        result["enum"] = [schema["const"]]
    if "properties" in schema:
        result["type"] = "object"
        result["properties"] = {name: plain_schema(value, definitions) for name, value in schema["properties"].items()}
        if schema.get("required"):
            result["required"] = schema["required"]
    if "items" in schema:
        result["items"] = plain_schema(schema["items"], definitions)
    if result.get("type") == "object":
        result.setdefault("properties", {})  # GigaChat требует это поле даже у пустого объекта
    return result


def _merged(variants: list[dict]) -> dict:
    properties: dict[str, dict] = {}
    for variant in variants:
        for name, field in variant.get("properties", {}).items():
            known = properties.setdefault(name, field)
            if known is not field and "enum" in known and "enum" in field:
                known["enum"] = sorted({*known["enum"], *field["enum"]})
    return {"type": "object", "properties": properties}


def _kept(schema: dict) -> dict:
    """Ограничения, которых нет в плоской схеме, переезжают в описание: иначе модель их не видит."""
    result = {key: schema[key] for key in KEPT_FIELDS if key in schema}
    limits = []
    if "maxLength" in schema:
        limits.append(f"Не длиннее {schema['maxLength']} символов.")
    if "pattern" in schema:
        limits.append(f"Формат: {schema['pattern']}.")
    if limits:
        result["description"] = " ".join(filter(None, (result.get("description"), *limits)))
    return result


def to_function(tool: dict) -> Function:
    return Function(name=tool["name"], description=tool["description"], parameters=plain_schema(tool["input_schema"]))


# --- Адаптер ---


class GigaChatLLM:
    def __init__(self, client: GigaChat | None = None, model: str | None = None):
        self.client = client or GigaChat(timeout=REQUEST_TIMEOUT_SECONDS, ca_bundle_file=str(ROOT_CERTIFICATE))
        self.model = model or os.environ.get("CAMPAIGN_LLM_MODEL", DEFAULT_MODEL)

    def complete(self, system: str, context: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        history = [Messages(role=MessagesRole.SYSTEM, content=f"{system}\n\n{context}")]
        for message in messages:
            history += to_gigachat(message)
        chat = Chat(
            model=self.model, messages=history, max_tokens=MAX_TOKENS, temperature=TEMPERATURE, repetition_penalty=REPETITION_PENALTY,
            functions=[to_function(tool) for tool in tools], function_call="auto",
        )
        def run() -> LLMResponse:
            response = parse_response(self._send(chat), self.model)
            if response.stop_reason == "max_tokens" and not response.tool_calls:  # модель зациклилась на одной фразе
                return parse_response(self._send(chat), self.model)
            return response

        return self._guarded(run)

    def draw(self, brief: str) -> bytes:
        """GigaChat сам вызывает генератор и отвечает тегом <img> с идентификатором файла."""
        def ask(text: str, **options) -> str:
            chat = Chat(model=self.model, messages=[Messages(role=MessagesRole.USER, content=text)], **options)
            return self._send(chat).choices[0].message.content or ""

        def run() -> bytes:
            # В рисунок идёт только предмет: слова рекламы генератор пишет на картинке или теряет тему.
            subject = ask(SUBJECT_PROMPT.format(brief=brief), temperature=TEMPERATURE).strip(" .\n")
            found = re.search(r'src="([^"]+)"', ask(IMAGE_PROMPT.format(subject=subject), function_call="auto"))
            if not found:
                raise LLMError("GigaChat не вернул изображение")
            return base64.b64decode(self.client.get_image(found.group(1)).content)

        return self._guarded(run)

    def _guarded(self, action):
        try:
            return action()
        except AuthenticationError as exc:
            raise LLMError("GigaChat не принял ключ: проверьте GIGACHAT_CREDENTIALS") from exc
        except RateLimitError as exc:
            raise LLMError("Лимит запросов к GigaChat исчерпан. Попробуйте позже.") from exc
        except GigaChatException as exc:
            raise LLMError(f"GigaChat вернул ошибку: {str(exc)[:200]}") from exc
        except (OSError, httpx.TransportError) as exc:
            raise LLMError("Не удалось соединиться с GigaChat") from exc

    def _send(self, chat: Chat):
        for delay in RETRY_DELAYS:  # разрыв и лимит на минуту обычно проходят за секунды
            try:
                return self.client.chat(chat)
            except (httpx.TransportError, RateLimitError):
                time.sleep(delay)
        return self.client.chat(chat)


def parse_response(response, model: str) -> LLMResponse:
    if not response.choices:
        return LLMResponse("", stop_reason="refusal", model=model)

    choice = response.choices[0]
    message = choice.message
    calls = []
    if message.function_call:
        arguments = message.function_call.arguments
        call_id = message.function_call.id_ or f"local-{uuid.uuid4().hex}"
        calls.append(ToolCall(call_id, message.function_call.name, arguments if isinstance(arguments, dict) else {}))

    if choice.finish_reason == "blacklist":
        stop_reason = "refusal"
    elif choice.finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "tool_use" if calls else "end_turn"
    return LLMResponse(message.content or "", calls, stop_reason, raw=message, model=model)


def to_gigachat(message: dict) -> list[Messages]:
    if message["role"] == "assistant":
        return [message["raw"]]
    if message["role"] == "user":
        return [Messages(role=MessagesRole.USER, content=message["text"])]

    result = []
    for item in message["results"]:
        content = item["content"] if isinstance(item["content"], dict) else {"result": item["content"]}
        # functions_state_id здесь нельзя: API отклоняет его в ответе функции.
        result.append(Messages(
            role=MessagesRole.FUNCTION, name=item["name"],
            id=None if item["id"].startswith("local-") else item["id"],
            content=json.dumps(content, ensure_ascii=False),
        ))
    if message.get("text"):
        result.append(Messages(role=MessagesRole.USER, content=message["text"]))
    return result
