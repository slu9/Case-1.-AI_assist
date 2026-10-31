"""Модели домена и каталог ошибок (task.md §2, §5)."""
from datetime import date, datetime, time
from enum import StrEnum
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import (
    BaseModel, ConfigDict, Field, HttpUrl, model_validator, StringConstraints, ValidationError,
)
from pydantic_core import PydanticCustomError


# --- Перечисления ---


class CampaignState(StrEnum):
    DRAFT = "DRAFT"
    ON_MODERATION = "ON_MODERATION"
    NEEDS_WORK = "NEEDS_WORK"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ACTIVE_EDITING = "ACTIVE_EDITING"
    STOPPED = "STOPPED"
    ARCHIVED = "ARCHIVED"


class AudienceType(StrEnum):
    ALL_USERS = "ALL_USERS"
    SEGMENTED = "SEGMENTED"


class ActionType(StrEnum):
    DEFAULT = "default"
    EXTERNAL_LINK = "externalLink"
    OPEN_SMART_LINK = "openSmartLink"
    CLOSE_CAMPAIGN = "closeCampaign"
    DONE_CAMPAIGN = "doneCampaign"


class FontWeight(StrEnum):
    THIN = "thin"
    LIGHT = "light"
    REGULAR = "regular"
    MEDIUM = "medium"
    SEMI_BOLD = "semi-bold"
    BOLD = "bold"


LINK_REQUIRED = {ActionType.EXTERNAL_LINK, ActionType.OPEN_SMART_LINK}
LINK_FORBIDDEN = {ActionType.CLOSE_CAMPAIGN, ActionType.DONE_CAMPAIGN}


# --- Баннер (§2.6) ---


HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{8}$"), Field(description="#RRGGBBAA, например #FFFFFFFF")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Link(Strict):
    iOS: str | None = None
    android: str | None = None
    web: str | None = None

    @model_validator(mode="after")
    def at_least_one_platform(self):
        if not (self.iOS or self.android or self.web):
            raise ValueError("в link нужна хотя бы одна платформа")
        return self


def check_link_rule(action_type: ActionType, link: Link | None) -> None:
    """Общее правило баннера и кнопки контента: actionType ↔ link."""
    if action_type in LINK_REQUIRED and link is None:
        raise PydanticCustomError("LINK_REQUIRED", f"link обязателен при actionType={action_type.value}")
    if action_type in LINK_FORBIDDEN and link is not None:
        raise PydanticCustomError("LINK_FORBIDDEN", f"link запрещён при actionType={action_type.value}")


class TextStyle(Strict):
    fontSize: int | None = Field(default=None, ge=10, le=40)
    fontWeight: FontWeight | None = None
    textColor: HexColor | None = None


class Background(Strict):
    color: HexColor


class HttpsImage(Strict):
    url: HttpUrl

    @model_validator(mode="after")
    def https_only(self):
        if self.url.scheme != "https":
            raise ValueError("image.url должен быть https-ссылкой")
        return self


class BannerContent(Strict):
    title: str | None = None
    text: str | None = None
    titleStyle: TextStyle | None = None
    textStyle: TextStyle | None = None
    background: Background | None = None
    image: HttpsImage | None = None
    buttonName: str | None = None
    actionType: ActionType
    link: Link | None = None
    voiceOver: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def link_matches_action(self):
        check_link_rule(self.actionType, self.link)
        return self


class BannerCreate(Strict):
    name: str = Field(min_length=1)
    bannerTypeId: int
    content: BannerContent


def check_banner_limits(content: BannerContent, banner_type: dict) -> list[str]:
    """Лимиты зависят от типа баннера, поэтому проверяются отдельно от схемы."""
    fields = []
    if content.title and len(content.title) > banner_type["titleMaxLength"]:
        fields.append("title")
    if content.text and len(content.text) > banner_type["textMaxLength"]:
        fields.append("text")
    return fields


# --- Контент PROMO (§2.7) ---


class TextComponent(Strict):
    role: Literal["text"]
    format: Literal["none", "html"]
    text: str
    textStyle: dict[str, Any] | None = None


class ImageComponent(Strict):
    role: Literal["image"]
    url: str = Field(min_length=1)
    aspectRatio: float | None = None


class ButtonComponent(Strict):
    role: Literal["button"]
    text: str
    actionType: ActionType
    link: Link | None = None
    textStyle: dict[str, Any] | None = None
    style: dict[str, Any] | None = None

    @model_validator(mode="after")
    def link_matches_action(self):
        check_link_rule(self.actionType, self.link)
        return self


Component = Annotated[TextComponent | ImageComponent | ButtonComponent, Field(discriminator="role")]


class LinearContainer(Strict):
    role: Literal["linearContainer"]
    axis: Literal["v"]
    aligns: str | None = None
    style: dict[str, Any] | None = None
    components: list[Component] = Field(min_length=1, max_length=6)


class PromoContent(Strict):
    role: Literal["promo"]
    component: LinearContainer


class ContentCreate(Strict):
    name: str = Field(min_length=1)
    contentType: Literal["PROMO"]
    content: PromoContent


# --- Креатив (§2.8) ---


class CreativeCreate(Strict):
    name: str = Field(min_length=1)
    bannerId: int
    contentId: int | None = None
    channelCode: str = Field(min_length=1)


def check_channel_allowed(channel_code: str, banner_type: dict) -> bool:
    return channel_code in banner_type["channels"]


HHmm = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class StrRef(Strict):
    value: str
    label: str


class IntRef(Strict):
    value: int
    label: str


# --- Шапка кампании и сегменты (§2.2, §2.4) ---


class CampaignInfo(Strict):
    name: str = Field(min_length=1, max_length=100)
    marketingName: str | None = Field(default=None, max_length=100)
    startDate: date
    startTime: HHmm
    endDate: date | None = None
    endTime: HHmm | None = None
    topic: StrRef
    tags: list[IntRef] = []
    keywords: str | None = Field(default=None, max_length=512)
    audienceType: AudienceType
    weight: float = 0.0
    initialCtr: float = 15.0
    places: list[IntRef] = []

    @model_validator(mode="after")
    def end_after_start(self):
        if self.endDate is None:
            return self
        start = datetime.combine(self.startDate, time.fromisoformat(self.startTime))
        end_time = time.fromisoformat(self.endTime) if self.endTime else time(23, 59)
        if datetime.combine(self.endDate, end_time) <= start:
            raise PydanticCustomError("DATE_RANGE_INVALID", "окончание показа должно быть позже начала")
        return self


class SegmentsUpdate(Strict):
    included: list[str] = []
    excluded: list[str] = []


class PlaceCreate(Strict):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TagCreate(Strict):
    name: str = Field(min_length=1)


NO_CREATIVE = "Не для всех мест показа настроены креативы"
INACTIVE_PLACE = "Некоторые места показа деактивированы"
NO_TAGS = "У кампании отсутствуют теги"


# --- Warnings (§4) ---


def campaign_warning_texts(places: list[dict], covered_banner_types: set[str], tags: list) -> list[str]:
    warnings = []
    if any(p["defaultBanner"] and p["defaultBanner"] not in covered_banner_types for p in places):
        warnings.append(NO_CREATIVE)
    if any(p["state"] != "ACTIVE" for p in places):
        warnings.append(INACTIVE_PLACE)
    if not tags:
        warnings.append(NO_TAGS)
    return warnings


AGE_ORDER = ["AGE_18_25", "AGE_26_45", "AGE_46_60", "AGE_60_PLUS"]


# --- Советы по аудитории ---


class Advisory(NamedTuple):
    code: str
    message: str


def check_audience(included: list[str], excluded: list[str]) -> list[Advisory]:
    advisories = []

    positions = sorted(AGE_ORDER.index(code) for code in set(included) if code in AGE_ORDER)
    if any(b - a > 1 for a, b in zip(positions, positions[1:])):
        groups = ", ".join(AGE_ORDER[i] for i in positions)
        advisories.append(Advisory(
            "AGE_GROUPS_NOT_ADJACENT",
            f"Возрастные группы идут не подряд ({groups}): уточните, что это намеренно. "
            "Для разных возрастов может понадобиться разный креатив.",
        ))

    overlap = [code for code in included if code in excluded]
    if overlap:
        advisories.append(Advisory(
            "SEGMENT_INCLUDED_AND_EXCLUDED",
            f"Сегменты есть и во включении, и в исключении ({', '.join(overlap)}): "
            "клиенты из них не увидят кампанию.",
        ))

    return advisories


VALIDATION_ERROR = "VALIDATION_ERROR"

MESSAGES = {
    "NAME_DUPLICATE": "Кампания с таким названием уже существует",
    "DATE_RANGE_INVALID": "Окончание показа должно быть позже начала",
    "SEGMENTS_FORBIDDEN_FOR_ALL_USERS": "Для аудитории «все пользователи» сегменты не задаются",
    "UPDATE_NOT_ALLOWED": "Кампанию нельзя редактировать в текущем состоянии",
    "TO_MODERATION_NOT_ALLOWED": "Кампанию нельзя отправить на модерацию в текущем состоянии",
    "DECLINE_NOT_ALLOWED": "Отклонить можно только кампанию на модерации",
    "APPROVE_NOT_ALLOWED": "Одобрить можно только кампанию на модерации",
    "ACTIVATE_NOT_ALLOWED": "Активировать можно только одобренную кампанию",
    "STOP_NOT_ALLOWED": "Остановить можно только кампанию с активным показом",
    "DELETE_NOT_ALLOWED": "Удалить можно только неопубликованную кампанию в DRAFT или NEEDS_WORK",
    "ROLE_FORBIDDEN": "Действие недоступно для вашей роли",
    "ENTITY_NOT_FOUND": "Сущность не найдена",
}


# --- Ошибки API (§3) ---


class ApiError(Exception):
    def __init__(self, errors: list[dict], status: int = 400):
        self.errors = errors
        self.status = status


def error(code: str, field: str | None = None, detail: str | None = None) -> dict:
    message = MESSAGES[code]
    return {"code": code, "message": f"{message}: {detail}" if detail else message, "field": field}


def invalid(message: str, field: str | None = None) -> dict:
    return {"code": VALIDATION_ERROR, "message": message, "field": field}


def fail(code: str, field: str | None = None, status: int = 400, detail: str | None = None):
    raise ApiError([error(code, field, detail)], status)


def reject(message: str, field: str | None = None):
    raise ApiError([invalid(message, field)])


def not_found(field: str, value) -> None:
    fail("ENTITY_NOT_FOUND", field, status=404, detail=f"{field}={value}")


def banner_limit_errors(content: BannerContent, banner_type: dict, prefix: str = "content") -> list[dict]:
    limits = {
        "title": ("Заголовок", len(content.title or ""), banner_type["titleMaxLength"]),
        "text": ("Текст", len(content.text or ""), banner_type["textMaxLength"]),
    }
    result = []
    for field in check_banner_limits(content, banner_type):
        label, length, limit = limits[field]
        result.append(invalid(f"{label}: {length} символов, лимит {banner_type['code']}: {limit}", f"{prefix}.{field}"))
    return result


def from_validation(exc: ValidationError) -> list[dict]:
    result = []
    for item in exc.errors():
        code = "DATE_RANGE_INVALID" if item["type"] == "DATE_RANGE_INVALID" else VALIDATION_ERROR
        field = ".".join(str(part) for part in item["loc"]) or None
        result.append({"code": code, "message": item["msg"], "field": field})
    return result


def check_schema(model: type[BaseModel], data: dict) -> list[dict]:
    try:
        model.model_validate(data)
    except ValidationError as exc:
        return from_validation(exc)
    return []
