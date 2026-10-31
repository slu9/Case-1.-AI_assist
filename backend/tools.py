"""Инструменты агента (task.md §6.2) и черновик в сессии.

write=True значит, что цикл агента не выполнит инструмент без подтверждения человека.
precheck запускается до показа подтверждения: заведомо невалидное действие сразу
возвращается модели с ошибками каталога и не отвлекает пользователя."""
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .domain import (
    Advisory, AudienceType, banner_limit_errors, BannerContent, BannerCreate, campaign_warning_texts,
    CampaignInfo, check_audience, check_channel_allowed, check_schema, ContentCreate, CreativeCreate, error,
    invalid, PlaceCreate, SegmentsUpdate, TagCreate,
)


DEFAULT_URL = "http://127.0.0.1:8000"


# --- Клиент бэкенда ---


class BackendError(Exception):
    def __init__(self, status: int, errors: list[dict]):
        super().__init__(errors)
        self.status = status
        self.errors = errors


class Backend:
    """X-User и X-Role приходят из сессии, а не от модели: роль нельзя подменить инструментом."""

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=os.environ.get("CAMPAIGN_API_URL", DEFAULT_URL))

    def request(self, method: str, path: str, user: str, role: str, body: dict | None = None):
        response = self.http.request(method, path, json=body, headers={"X-User": user, "X-Role": role})
        if response.status_code >= 400:
            raise BackendError(response.status_code, response.json().get("errors", []))
        return response.json() if response.content else {"ok": True}


# --- Черновик ---


class CampaignFields(BaseModel):
    """Поля шапки для модели: справочные значения сырые, обёртку {value, label} ставит код."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Название, уникальное, до 100 символов")
    marketingName: str | None = None
    startDate: str | None = Field(default=None, description="YYYY-MM-DD")
    startTime: str | None = Field(default=None, description="HH:mm, UTC")
    endDate: str | None = None
    endTime: str | None = None
    topic: str | None = Field(default=None, description="value из get_topics")
    tags: list[int] | None = Field(default=None, description="id из get_tags")
    keywords: str | None = Field(default=None, description="Через ';'")
    audienceType: AudienceType | None = None
    weight: float | None = None
    initialCtr: float | None = None
    places: list[int] | None = Field(default=None, description="id из get_places")


class DraftCampaignFields(CampaignFields):
    noEndDate: bool | None = Field(default=None, description="true, только если менеджер прямо сказал, что окончания нет")


CAMPAIGN_KEYS = tuple(CampaignFields.model_fields)


@dataclass
class Dictionaries:
    topics: list[dict]
    tags: list[dict]
    places: list[dict]
    segments: list[dict]
    banner_types: list[dict]
    channels: list[dict]
    campaign_names: dict[str, int]


def wrap_refs(raw: dict, d: Dictionaries) -> dict:
    """Формат тел POST/PUT (task.md §2.2): label берётся из справочника."""
    topics = {t["value"]: t["label"] for t in d.topics}
    tags = {t["id"]: t["name"] for t in d.tags}
    places = {p["id"]: p["code"] for p in d.places}

    payload = {k: v for k, v in raw.items() if v is not None}
    if "topic" in payload:
        payload["topic"] = {"value": payload["topic"], "label": topics.get(payload["topic"], "")}
    payload["tags"] = [{"value": i, "label": tags.get(i, "")} for i in raw.get("tags") or []]
    payload["places"] = [{"value": i, "label": places.get(i, "")} for i in raw.get("places") or []]
    return payload


def campaign_payload_errors(raw: dict, d: Dictionaries, own_id: int | None = None) -> list[dict]:
    errors = check_schema(CampaignInfo, wrap_refs(raw, d))

    topic = raw.get("topic")
    if topic and topic not in {t["value"] for t in d.topics}:
        errors.append(invalid(f"Нет такой тематики: {topic}", "topic"))
    for tag in raw.get("tags") or []:
        if tag not in {t["id"] for t in d.tags}:
            errors.append(error("ENTITY_NOT_FOUND", "tags", f"tags={tag}"))
    for place in raw.get("places") or []:
        if place not in {p["id"] for p in d.places}:
            errors.append(error("ENTITY_NOT_FOUND", "places", f"places={place}"))

    same_name = d.campaign_names.get(raw.get("name"))
    if same_name is not None and same_name != own_id:
        errors.append(error("NAME_DUPLICATE", "name", raw["name"]))
    return errors


def banner_errors(body: dict, d: Dictionaries) -> list[dict]:
    errors = check_schema(BannerCreate, body)
    if errors:
        return errors
    banner_type = next((t for t in d.banner_types if t["id"] == body["bannerTypeId"]), None)
    if banner_type is None:
        return [error("ENTITY_NOT_FOUND", "bannerTypeId", f"bannerTypeId={body['bannerTypeId']}")]
    return banner_limit_errors(BannerContent.model_validate(body["content"]), banner_type)


def content_errors(body: dict) -> list[dict]:
    return check_schema(ContentCreate, body)


def dictionaries_context(d: Dictionaries) -> str:
    """Справочники для модели на каждый ход: на чтение инструментами уходила бы квота запросов."""
    keys = ("code", "name", "type", "state", "count")
    data = {
        "тематики": [{"value": t["value"], "label": t["label"]} for t in d.topics],
        "известные_адреса": KNOWN_LINKS,
        "теги": d.tags,
        "места_показа": d.places,
        "сегменты": [{key: s[key] for key in keys} for s in d.segments],
        "типы_баннеров": d.banner_types,
        "каналы": [c["code"] for c in d.channels],
    }
    return "Актуальные справочники:\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def audience_summary(included: list[str], excluded: list[str], d: Dictionaries) -> dict:
    """Сумма count не считается: пересечений между сегментами в данных нет."""
    by_code = {s["code"]: s for s in d.segments}

    def describe(codes):
        return [
            {key: by_code[code][key] for key in ("code", "name", "type", "state", "count")}
            for code in codes if code in by_code
        ]

    return {
        "included": describe(included),
        "excluded": describe(excluded),
        "semantics": "Клиент попадает в кампанию, если входит в ЛЮБОЙ сегмент включения "
                     "и не входит ни в один сегмент исключения",
    }


@dataclass
class Draft:
    campaign: dict[str, Any] = field(default_factory=dict)
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    banners: dict[str, dict] = field(default_factory=dict)  # key -> тело POST
    contents: dict[str, dict] = field(default_factory=dict)
    creatives: list[dict] = field(default_factory=list)  # name, bannerKey, contentKey, channelCode

    # Что уже записано в бэкенд: повторное применение продолжает с упавшего шага.
    campaign_id: int | None = None
    segments_saved: bool = False
    banner_ids: dict[str, int] = field(default_factory=dict)
    content_ids: dict[str, int] = field(default_factory=dict)
    creatives_saved: set[tuple[str, str]] = field(default_factory=set)  # bannerKey, channelCode
    finished: bool = False
    open_ended: bool = False
    manual_weight: bool = False
    source_text: str = ""  # тексты открытой кампании: числа из них не считаются выдуманными
    weight_reasons: list[str] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "campaign": self.campaign,
            "segments": {"included": self.included, "excluded": self.excluded},
            "banners": self.banners,
            "contents": self.contents,
            "creatives": self.creatives,
            "campaignId": self.campaign_id,
            "finished": self.finished,
            "weightReasons": self.weight_reasons,
        }

    def bind_single_content(self) -> None:
        """Единственный PROMO-экран открывается из всех креативов, модели не нужно это повторять."""
        if len(self.contents) == 1:
            key = next(iter(self.contents))
            for creative in self.creatives:
                creative["contentKey"] = creative.get("contentKey") or key

    def errors(self, d: Dictionaries) -> list[dict]:
        errors = campaign_payload_errors(self.campaign, d, self.campaign_id)

        if not self.campaign.get("places"):
            errors.append(invalid("Не задано ни одного места показа", "places"))
        audience = self.campaign.get("audienceType")
        if audience == AudienceType.SEGMENTED and not self.included:
            errors.append(invalid("Нужен хотя бы один сегмент включения", "segments.included"))
        if audience == AudienceType.ALL_USERS and (self.included or self.excluded):
            errors.append(error("SEGMENTS_FORBIDDEN_FOR_ALL_USERS", "segments"))

        segments = {s["code"]: s for s in d.segments}
        for name, codes in (("included", self.included), ("excluded", self.excluded)):
            for code in codes:
                if code not in segments:
                    errors.append(invalid(f"Нет такого сегмента: {code}", name))
                elif segments[code]["state"] != "ACTIVE":
                    errors.append(invalid(f"Сегмент {code} не активен, выбрать его нельзя", name))

        for body in self.banners.values():
            errors += banner_errors(body, d)
        for body in self.contents.values():
            errors += content_errors(body)
        errors += self._creative_errors(d)
        return errors

    def _creative_errors(self, d: Dictionaries) -> list[dict]:
        errors = []
        types = {t["id"]: t for t in d.banner_types}
        seen = set()
        for creative in self.creatives:
            banner = self.banners.get(creative["bannerKey"])
            if banner is None:
                errors.append(error("ENTITY_NOT_FOUND", "bannerKey", creative["bannerKey"]))
                continue
            content_key = creative.get("contentKey")
            if content_key and content_key not in self.contents:
                errors.append(error("ENTITY_NOT_FOUND", "contentKey", content_key))

            channel = creative["channelCode"]
            banner_type = types.get(banner["bannerTypeId"])
            if channel not in {c["code"] for c in d.channels}:
                errors.append(error("ENTITY_NOT_FOUND", "channelCode", channel))
            elif banner_type and not check_channel_allowed(channel, banner_type):
                errors.append(invalid(f"Канал {channel} не разрешён для типа {banner_type['code']}", "channelCode"))

            pair = (creative["bannerKey"], channel)
            if pair in seen:
                errors.append(invalid(f"Креатив {pair[0]} на канале {channel} указан дважды", "channelCode"))
            seen.add(pair)
        return errors

    def warnings(self, d: Dictionaries) -> list[str]:
        types = {t["id"]: t["code"] for t in d.banner_types}
        covered = {
            types.get(self.banners[c["bannerKey"]]["bannerTypeId"])
            for c in self.creatives if c["bannerKey"] in self.banners
        }
        selected = set(self.campaign.get("places") or [])
        return campaign_warning_texts(
            [p for p in d.places if p["id"] in selected], covered, self.campaign.get("tags"),
        )

    def advisories(self) -> list[dict]:
        advisories = [a._asdict() for a in check_audience(self.included, self.excluded)]
        if self.creatives and any(not c.get("contentKey") for c in self.creatives):
            advisories.append(Advisory(
                "CREATIVE_WITHOUT_CONTENT",
                "У креатива нет промо-экрана: по нажатию на баннер ничего не откроется.",
            )._asdict())
        return advisories

    def review(self, d: Dictionaries) -> dict:
        errors = self.errors(d)
        return {
            "ready": not errors,
            "errors": errors,
            "warnings": self.warnings(d),
            "advisories": self.advisories(),
            "audience": audience_summary(self.included, self.excluded, d),
        }


@dataclass
class Context:
    backend: Backend
    user: str
    role: str
    draft: Draft
    brief: str = ""  # всё, что написал человек: источник условий для текстов
    last_message: str = ""

    def call(self, method: str, path: str, body: dict | None = None):
        return self.backend.request(method, path, self.user, self.role, body)

    def dictionaries(self) -> Dictionaries:
        get = lambda path: self.call("GET", path)  # noqa: E731
        return Dictionaries(
            topics=get("/topics"),
            tags=get("/tags"),
            places=get("/places"),
            segments=get("/segments"),
            banner_types=get("/banner-types"),
            channels=get("/channels"),
            campaign_names={c["name"]: c["id"] for c in get("/campaigns")},
        )


# --- Описание инструмента ---


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[[Context, dict], Any]
    write: bool = False
    method: str | None = None
    path: str | None = None
    precheck: Callable[[Context, dict], list[dict]] | None = None

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


TOPIC_WEIGHT = {
    "EVENT": 6, "SALES": 5, "RETARGET": 5, "LIFESTYLE": 4, "EXTRA": 3, "RECOMMENDATION": 3,
    "FINANCIAL_TIPS": 2, "ADVICES": 2, "HINTS": 2, "COURSES": 2,
}
MAX_WEIGHT = 12
PRIORITY = re.compile(r"(широк|максимальн)\w* охват|приоритет|срочн|важн", re.IGNORECASE)
MANUAL_WEIGHT = re.compile(r"\bвес", re.IGNORECASE)
CONDITION = re.compile(r"\b[A-Za-z]+\d+[A-Za-z\d]*\b|\d+(?:[.,]\d+)?\s*%?")
MENTIONED_CAMPAIGN = re.compile(r"кампани\w*\s*(?:№\s*)?(\d{3,})", re.IGNORECASE)
NEW_CAMPAIGN = re.compile(r"нов\w+ кампани|по образцу|скопируй|копи\w+", re.IGNORECASE)
MODERATION_REQUEST = re.compile(r"модерац|отправ", re.IGNORECASE)
KNOWN_LINKS = (
    "mobilebank://insurance/travel", "mobilebank://loans/auto", "mobilebank://payments/auto_payments",
    "mobilebank://payments/transfer", "mobilebank://products/card/premium", "mobilebank://promo/winter-marathon",
    "mobilebank://travel/hotels", "mobilebank://travel/main",
)
NO_INPUT = {"type": "object", "properties": {}, "additionalProperties": False}


def path_params(path: str) -> list[str]:
    return re.findall(r"{(\w+)}", path)


def with_ids(model: type[BaseModel] | None, ids: list[str]) -> dict:
    """Схема тела запроса плюс идентификаторы из пути."""
    schema = model.model_json_schema() if model else dict(NO_INPUT)
    schema["properties"] = {**{i: {"type": "integer"} for i in ids}, **schema.get("properties", {})}
    schema["required"] = ids + schema.get("required", [])
    return schema


def api_tool(name: str, method: str, path: str, description: str, model=None, write=True, precheck=None, extra=None) -> Tool:
    ids = path_params(path)
    schema = with_ids(model, ids)
    if extra:
        schema["properties"].update(extra)
        schema["required"] += list(extra)

    def run(ctx: Context, data: dict):
        body = {k: v for k, v in data.items() if k not in ids}
        return ctx.call(method, path.format(**data), body if method in ("POST", "PUT") and body else None)

    return Tool(name, description, schema, run, write, method, path, precheck)


def bound(field_name: str, *args, **kwargs) -> Tool:
    """Новая запись справочника сразу попадает в черновик: создание и привязка одним шагом (task.md §10.4)."""
    tool = api_tool(*args, **kwargs)

    def run(ctx: Context, data: dict):
        created = tool.run(ctx, data)
        if not ctx.draft.finished:
            ids = ctx.draft.campaign.get(field_name) or []
            ctx.draft.campaign[field_name] = [*ids, created["id"]] if created["id"] not in ids else ids
        return created

    return replace(tool, run=run)


def body_of(data: dict) -> dict:
    return {k: v for k, v in data.items() if not k.endswith("Id") or k == "bannerTypeId"}


def banner_precheck(ctx: Context, data: dict) -> list[dict]:
    return banner_errors(body_of(data), ctx.dictionaries())


def content_precheck(ctx: Context, data: dict) -> list[dict]:
    return content_errors(body_of(data))


def creative_precheck(ctx: Context, data: dict) -> list[dict]:
    return check_schema(CreativeCreate, {k: v for k, v in data.items() if k != "campaignId" and k != "creativeId"})


# --- Кампания: модель передаёт сырые значения, обёртку и слияние делает код ---

def campaign_fields(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in CAMPAIGN_KEYS}


def create_precheck(ctx: Context, data: dict) -> list[dict]:
    return campaign_payload_errors(campaign_fields(data), ctx.dictionaries())


def create_campaign(ctx: Context, data: dict):
    return ctx.call("POST", "/campaigns", wrap_refs(campaign_fields(data), ctx.dictionaries()))


def merged_update(ctx: Context, data: dict) -> dict:
    """PUT это полная замена, поэтому частичная правка идёт через GET и слияние (task.md §3)."""
    current = ctx.call("GET", f"/campaigns/{data['campaignId']}")
    return {**{k: current[k] for k in CAMPAIGN_KEYS}, **campaign_fields(data)}


def update_precheck(ctx: Context, data: dict) -> list[dict]:
    return campaign_payload_errors(merged_update(ctx, data), ctx.dictionaries(), data["campaignId"])


def update_campaign(ctx: Context, data: dict):
    payload = wrap_refs(merged_update(ctx, data), ctx.dictionaries())
    return ctx.call("PUT", f"/campaigns/{data['campaignId']}", payload)


# --- Черновик ---

class DraftCreative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    bannerKey: str
    contentKey: str | None = None
    channelCode: str = Field(description="iOS, ANDROID или WEB")


class DraftCreatives(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creatives: list[DraftCreative]


# --- Инструменты черновика ---


def suggest_weight(campaign: dict, brief: str) -> dict:
    """Вес для ранжирования в местах показа (task.md §2.2, §6): шкала как в моках, от 0 до 12."""
    parts = {"тема": TOPIC_WEIGHT.get(campaign.get("topic"), 1)}
    if campaign.get("startDate") and campaign.get("endDate"):
        days = (date.fromisoformat(campaign["endDate"]) - date.fromisoformat(campaign["startDate"])).days
        parts["короткий срок"] = 3 if days <= 14 else 2 if days <= 31 else 1 if days <= 62 else 0
    if campaign.get("audienceType") == "ALL_USERS":
        parts["широкая аудитория"] = 2
    if PRIORITY.search(brief):
        parts["приоритет в брифе"] = 2
    return {
        "weight": float(min(MAX_WEIGHT, sum(parts.values()))),
        "reasons": [f"{name} +{value}" for name, value in parts.items() if value],
    }


def refresh_weight(ctx: Context) -> None:
    if not ctx.draft.manual_weight:
        advice = suggest_weight(ctx.draft.campaign, ctx.brief)
        ctx.draft.campaign["weight"] = advice["weight"]
        ctx.draft.weight_reasons = advice["reasons"]


def draft_update_campaign(ctx: Context, data: dict):
    ctx.draft.open_ended = data.pop("noEndDate", ctx.draft.open_ended) or False
    weight = data.pop("weight", None)
    if weight is not None and MANUAL_WEIGHT.search(ctx.brief):  # своё значение только по просьбе менеджера
        ctx.draft.campaign["weight"], ctx.draft.manual_weight, ctx.draft.weight_reasons = weight, True, []
    ctx.draft.campaign.update(data)
    refresh_weight(ctx)
    return {"ok": True, "campaign": ctx.draft.campaign, "weightReasons": ctx.draft.weight_reasons}


def draft_set_segments(ctx: Context, data: dict):
    ctx.draft.included = data.get("included", [])
    ctx.draft.excluded = data.get("excluded", [])
    return ctx.draft.review(ctx.dictionaries())["audience"]


def banner_tool_schema() -> dict:
    """Для модели заголовок и текст обязательны: схема API их не требует, и она оставляла баннер пустым."""
    schema = BannerCreate.model_json_schema()
    content = schema["$defs"]["BannerContent"]
    content["required"] = ["title", "text", *content["required"]]
    del content["properties"]["voiceOver"]  # озвучка строится из заголовка
    return {**schema, "properties": {**KEY, **schema["properties"]}, "required": ["key", *schema["required"]]}


def clean_banner(content: dict) -> dict:
    """Пустая ссылка и длинная озвучка не повод для ошибки: их смысл не меняется."""
    cleaned = {key: value for key, value in content.items() if value not in (None, "", {})}
    if not any((cleaned.get("link") or {}).values()):
        cleaned.pop("link", None)
    cleaned["voiceOver"] = str(cleaned.get("voiceOver") or cleaned.get("title") or "")[:200]
    return {key: value for key, value in cleaned.items() if value != ""}


def draft_upsert_banner(ctx: Context, data: dict):
    key, body = data["key"], {k: v for k, v in data.items() if k != "key"}
    body["content"] = clean_banner(body.get("content") or {})
    without_unknown_links(ctx, body["content"], "default")
    errors = banner_errors(body, ctx.dictionaries())
    if errors:
        raise BackendError(400, errors)
    ctx.draft.banners[key] = body
    return {"ok": True, "key": key}


def draft_upsert_content(ctx: Context, data: dict):
    key, body = data["key"], {k: v for k, v in data.items() if k != "key"}
    for item in (body.get("content") or {}).get("component", {}).get("components", []):
        if isinstance(item, dict) and item.get("role") == "button":
            without_unknown_links(ctx, item, "closeCampaign")
    errors = content_errors(body)
    if errors:
        raise BackendError(400, errors)
    ctx.draft.contents[key] = body
    ctx.draft.bind_single_content()
    return {"ok": True, "key": key}


def draft_set_creatives(ctx: Context, data: dict):
    ctx.draft.creatives = data["creatives"]
    ctx.draft.bind_single_content()
    return {"ok": True, "count": len(data["creatives"])}


def lifecycle_facts(state: str, published: bool) -> dict:
    """Ответ о кампании несёт готовые правила §2.3: так модель не сочиняет их сама."""
    facts = {
        "можно_править": state in ("DRAFT", "NEEDS_WORK", "APPROVED", "ACTIVE", "ACTIVE_EDITING"),
        "можно_на_модерацию": state in ("DRAFT", "NEEDS_WORK", "ACTIVE_EDITING"),
        "можно_активировать": state == "APPROVED",
        "можно_остановить": published,
        "можно_удалить": state in ("DRAFT", "NEEDS_WORK") and not published,
    }
    allowed = [name for name, value in facts.items() if value]
    return {
        **facts,
        "вывод": f"Возможны только: {', '.join(allowed) or 'никакие действия'}. Других путей нет. "
                 "После остановки кампанию нельзя ни возобновить, ни удалить. Снять с модерации может только модератор.",
    }


def get_campaign(ctx: Context, data: dict):
    campaign = ctx.call("GET", f"/campaigns/{data['campaignId']}")
    return {**campaign, "lifecycle": lifecycle_facts(campaign["state"], campaign["published"])}


def draft_open_campaign(ctx: Context, data: dict):
    """Существующая кампания правится тем же черновиком: apply_draft обновит её, а не создаст копию."""
    current = ctx.call("GET", f"/campaigns/{data['campaignId']}")
    banners = {f"banner{row['id']}": row for row in current["banners"]}
    contents = {f"content{row['id']}": row for row in current["contents"]}
    banner_keys = {row["id"]: key for key, row in banners.items()}
    content_keys = {row["id"]: key for key, row in contents.items()}
    creatives = [
        {
            "name": row["name"], "bannerKey": banner_keys[row["bannerId"]],
            "contentKey": content_keys.get(row["contentId"]), "channelCode": row["channelCode"],
        }
        for row in current["creatives"]
    ]
    pick = lambda row, *keys: {key: row[key] for key in keys}  # noqa: E731
    ctx.draft.__init__(
        campaign={key: current[key] for key in CAMPAIGN_KEYS},
        included=current["segments"]["included"], excluded=current["segments"]["excluded"],
        banners={key: pick(row, "name", "bannerTypeId", "content") for key, row in banners.items()},
        contents={key: pick(row, "name", "contentType", "content") for key, row in contents.items()},
        creatives=creatives, campaign_id=current["id"], segments_saved=True,
        banner_ids={key: row["id"] for key, row in banners.items()},
        content_ids={key: row["id"] for key, row in contents.items()},
        creatives_saved={(row["bannerKey"], row["channelCode"]) for row in creatives},
        open_ended=current["endDate"] is None, manual_weight=bool(current["weight"]),
        source_text=json.dumps([current["banners"], current["contents"]], ensure_ascii=False),
    )
    return {"ok": True, "state": current["state"], "draft": ctx.draft.snapshot()}


def draft_review(ctx: Context, _: dict):
    refresh_weight(ctx)
    return {**ctx.draft.review(ctx.dictionaries()), "weightReasons": ctx.draft.weight_reasons}


def draft_reset(ctx: Context, _: dict):
    ctx.draft.__init__()
    return {"ok": True}


def creative_texts(value) -> list[str]:
    if isinstance(value, dict):
        own = [v for k, v in value.items() if k in ("title", "text", "voiceOver") and isinstance(v, str)]
        return own + [text for v in value.values() for text in creative_texts(v)]
    if isinstance(value, list):
        return [text for v in value for text in creative_texts(v)]
    return []


def links_of(value) -> list[str]:
    if isinstance(value, dict):
        own = [v for v in (value.get("link") or {}).values() if v]
        return own + [link for v in value.values() for link in links_of(v)]
    if isinstance(value, list):
        return [link for v in value for link in links_of(v)]
    return []


def source_of(ctx: Context) -> str:
    return f"{ctx.brief} {ctx.draft.source_text}"


def condition_key(item: str) -> str:
    return item.lower().rstrip(" %")


def link_is_known(ctx: Context, link: str) -> bool:
    return link in KNOWN_LINKS or link in source_of(ctx)


def without_unknown_links(ctx: Context, holder: dict, fallback: str) -> None:
    """Выдуманный адрес убирается сразу: модель иначе тратит ходы, снова подставляя его."""
    link = {key: url for key, url in (holder.get("link") or {}).items() if url and link_is_known(ctx, url)}
    if link:
        holder["link"] = link
        return
    holder.pop("link", None)
    if holder.get("actionType") in ("externalLink", "openSmartLink"):
        holder["actionType"] = fallback


def invented_conditions(ctx: Context) -> list[str]:
    """Числа, промокоды и адреса, которых нет ни в словах человека, ни в открытой кампании."""
    draft = ctx.draft
    source = source_of(ctx)
    known = {condition_key(item) for item in CONDITION.findall(source)}
    phrases = {
        f"«{item.strip()}» во фразе «{text}»"
        for text in creative_texts([draft.banners, draft.contents])
        for item in CONDITION.findall(text) if condition_key(item) not in known
    }
    links = {link for link in links_of([draft.banners, draft.contents]) if not link_is_known(ctx, link)}
    return sorted(phrases | links)


def moderation_precheck(ctx: Context, _: dict) -> list[dict]:
    if MODERATION_REQUEST.search(ctx.last_message):
        return []
    return [invalid("Менеджер не просил отправлять на модерацию. Предложи это вопросом и дождись ответа")]


def apply_precheck(ctx: Context, _: dict) -> list[dict]:
    if ctx.draft.finished:
        return [invalid(
            f"Черновик уже применён, кампания {ctx.draft.campaign_id}. "
            "Правьте её инструментами кампании или начните новую через draft_reset"
        )]
    if ctx.draft.campaign_id is None and not NEW_CAMPAIGN.search(ctx.brief):
        if mentioned := MENTIONED_CAMPAIGN.search(ctx.brief):
            return [invalid(f"Менеджер говорит о кампании {mentioned[1]}: открой её через draft_open_campaign и не создавай новую")]
    refresh_weight(ctx)
    errors = ctx.draft.errors(ctx.dictionaries())
    if not ctx.draft.campaign.get("endDate") and not ctx.draft.open_ended:
        errors.append(invalid(
            "Не указано окончание показа. Спросите менеджера о дате окончания и предложите варианты. "
            "Если окончания нет по его прямым словам, передайте noEndDate", "endDate",
        ))
    for key, banner in ctx.draft.banners.items():
        if not banner["content"].get("title") and not banner["content"].get("image"):
            errors.append(invalid(f"В баннере {key} нет заголовка: сводка должна совпадать с черновиком", f"banners.{key}"))
    if ctx.draft.contents and any(not creative.get("contentKey") for creative in ctx.draft.creatives):
        errors.append(invalid("PROMO-экран собран, но не привязан к креативам: укажите contentKey", "creatives"))
    if invented := invented_conditions(ctx):
        errors.append(invalid(
            f"В креативе есть данные не из брифа: {', '.join(invented)}. Перепиши эту фразу через draft_upsert_banner или draft_upsert_content без них и только потом вызывай apply_draft", "banners",
        ))
    if not ctx.draft.creatives and ctx.draft.campaign_id is None:
        errors.append(invalid("В черновике нет креативов: сначала соберите баннер, PROMO-экран и креативы", "creatives"))
    return errors


def apply_draft(ctx: Context, _: dict):
    """Цепочка записи без участия модели. Каждый шаг запоминается, поэтому при сбое
    повторный вызов продолжает с упавшего шага и не создаёт дубликатов."""
    draft = ctx.draft
    d = ctx.dictionaries()

    payload = wrap_refs(draft.campaign, d)
    if draft.campaign_id is None:
        draft.campaign_id = ctx.call("POST", "/campaigns", payload)["id"]
    else:
        ctx.call("PUT", f"/campaigns/{draft.campaign_id}", payload)  # черновик могли поправить после сбоя
    base = f"/campaigns/{draft.campaign_id}"

    if draft.included or draft.excluded or draft.segments_saved:
        ctx.call("PUT", f"{base}/segments", {"included": draft.included, "excluded": draft.excluded})
        draft.segments_saved = True

    for key, body in draft.banners.items():
        if key in draft.banner_ids:
            ctx.call("PUT", f"{base}/banners/{draft.banner_ids[key]}", body)
        else:
            draft.banner_ids[key] = ctx.call("POST", f"{base}/banners", body)["id"]
    for key, body in draft.contents.items():
        if key in draft.content_ids:
            ctx.call("PUT", f"{base}/contents/{draft.content_ids[key]}", body)
        else:
            draft.content_ids[key] = ctx.call("POST", f"{base}/contents", body)["id"]

    for creative in draft.creatives:
        pair = (creative["bannerKey"], creative["channelCode"])
        if pair in draft.creatives_saved:
            continue
        ctx.call("POST", f"{base}/creatives", {
            "name": creative["name"],
            "bannerId": draft.banner_ids[creative["bannerKey"]],
            "contentId": draft.content_ids.get(creative.get("contentKey")),
            "channelCode": creative["channelCode"],
        })
        draft.creatives_saved.add(pair)

    draft.finished = True
    return {"campaignId": draft.campaign_id, **ctx.call("GET", f"{base}/warnings")}


KEY = {"key": {"type": "string", "description": "Ключ сущности внутри черновика, например story"}}

_C = "/campaigns/{campaignId}"

# --- Каталог инструментов ---


API_TOOLS = [
    api_tool("get_topics", "GET", "/topics", "Справочник тематик", write=False),
    api_tool("get_tags", "GET", "/tags", "Справочник тегов", write=False),
    api_tool("get_channels", "GET", "/channels", "Каналы показа", write=False),
    api_tool("get_banner_types", "GET", "/banner-types", "Типы баннеров: лимиты и допустимые каналы", write=False),
    api_tool("get_segment_types", "GET", "/segment-types", "Типы сегментов", write=False),
    api_tool("get_segments", "GET", "/segments", "Сегменты аудитории с числом клиентов и состоянием", write=False),
    api_tool("get_places", "GET", "/places", "Места показа, их тип баннера и состояние", write=False),
    api_tool("list_campaigns", "GET", "/campaigns", "Список кампаний", write=False),
    replace(
        api_tool("get_campaign", "GET", _C, "Кампания со всеми дочерними сущностями и правилами её состояния", write=False),
        run=get_campaign,
    ),
    api_tool("get_campaign_warnings", "GET", f"{_C}/warnings", "Прогон валидации: ошибки и warnings", write=False),
    api_tool("get_campaign_audit", "GET", f"{_C}/audit", "Журнал аудита, включая комментарии модератора", write=False),
    bound("places", "create_place", "POST", "/places", "Создать место показа, которого нет в справочнике", PlaceCreate),
    bound("tags", "create_tag", "POST", "/tags", "Создать тег, которого нет в справочнике", TagCreate),
    Tool(
        "create_campaign", "Создать кампанию напрямую, без черновика",
        CampaignFields.model_json_schema(), create_campaign, True, "POST", "/campaigns", create_precheck,
    ),
    Tool(
        "update_campaign", "Изменить поля существующей кампании: передавайте только то, что меняется",
        with_ids(CampaignFields, ["campaignId"]), update_campaign, True, "PUT", _C, update_precheck,
    ),
    api_tool("delete_campaign", "DELETE", _C, "Удалить кампанию"),
    api_tool("update_segments", "PUT", f"{_C}/segments", "Заменить сегменты существующей кампании", SegmentsUpdate),
    api_tool("create_banner", "POST", f"{_C}/banners", "Добавить баннер в кампанию", BannerCreate, precheck=banner_precheck),
    api_tool("update_banner", "PUT", f"{_C}/banners/{{bannerId}}", "Заменить баннер целиком", BannerCreate, precheck=banner_precheck),
    api_tool("delete_banner", "DELETE", f"{_C}/banners/{{bannerId}}", "Удалить баннер вместе с его креативами"),
    api_tool("create_content", "POST", f"{_C}/contents", "Добавить PROMO-экран в кампанию", ContentCreate, precheck=content_precheck),
    api_tool("update_content", "PUT", f"{_C}/contents/{{contentId}}", "Заменить PROMO-экран целиком", ContentCreate, precheck=content_precheck),
    api_tool("delete_content", "DELETE", f"{_C}/contents/{{contentId}}", "Удалить PROMO-экран и отвязать его от креативов"),
    api_tool("create_creative", "POST", f"{_C}/creatives", "Связать баннер, контент и канал", CreativeCreate, precheck=creative_precheck),
    api_tool("update_creative", "PUT", f"{_C}/creatives/{{creativeId}}", "Заменить креатив целиком", CreativeCreate, precheck=creative_precheck),
    api_tool("delete_creative", "DELETE", f"{_C}/creatives/{{creativeId}}", "Удалить креатив"),
    api_tool("to_moderation", "POST", f"{_C}/to-moderation", "Отправить кампанию на модерацию", precheck=moderation_precheck),
    api_tool(
        "decline_campaign", "POST", f"{_C}/decline", "Отклонить кампанию с комментарием (только модератор)",
        extra={"comment": {"type": "string"}},
    ),
    api_tool("approve_campaign", "POST", f"{_C}/approve", "Одобрить кампанию (только модератор)"),
    api_tool("activate_campaign", "POST", f"{_C}/activate", "Запустить показ одобренной кампании"),
    api_tool("stop_campaign", "POST", f"{_C}/stop", "Остановить показ"),
]

DRAFT_TOOLS = [
    Tool("draft_update_campaign", "Заполнить поля шапки в черновике: передавайте только известные поля",
         DraftCampaignFields.model_json_schema(), draft_update_campaign),
    Tool("draft_set_segments", "Задать сегменты в черновике; возвращает их описание и смысл объединения",
         SegmentsUpdate.model_json_schema(), draft_set_segments),
    Tool("draft_upsert_banner", "Добавить или заменить баннер в черновике; JSON проверяется по схеме",
         banner_tool_schema(), draft_upsert_banner),
    Tool("draft_upsert_content", "Добавить или заменить PROMO-экран в черновике; JSON проверяется по схеме",
         {**(s := ContentCreate.model_json_schema()), "properties": {**KEY, **s["properties"]},
          "required": ["key", *s["required"]]}, draft_upsert_content),
    Tool("draft_set_creatives", "Задать креативы черновика: связи баннера, контента и канала по ключам",
         DraftCreatives.model_json_schema(), draft_set_creatives),
    Tool("draft_open_campaign", "Открыть существующую кампанию в черновике, чтобы исправить её и сохранить через apply_draft",
         {"type": "object", "properties": {"campaignId": {"type": "integer"}}, "required": ["campaignId"]},
         draft_open_campaign),
    Tool("draft_review", "Проверить черновик: ошибки, warnings, советы и описание аудитории", NO_INPUT, draft_review),
    Tool("draft_reset", "Очистить черновик, чтобы начать новую кампанию", NO_INPUT, draft_reset),
    Tool("apply_draft", "Записать проверенный черновик в систему: кампания, сегменты, баннеры, контент, креативы",
         NO_INPUT, apply_draft, write=True, precheck=apply_precheck),
]

TOOLS = {tool.name: tool for tool in API_TOOLS + DRAFT_TOOLS}
