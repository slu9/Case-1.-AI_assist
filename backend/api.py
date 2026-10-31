"""Бэкенд по task.md §3: запуск uvicorn --factory backend.api:create_app --reload."""
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import (
    AuditEntry, Banner, BannerType, Campaign, Channel, Content, Creative, DEFAULT_DB, make_engine, Place,
    seed, Segment, SegmentType, Tag, Topic,
)
from .domain import (
    ApiError, AudienceType, banner_limit_errors, BannerContent, BannerCreate, campaign_warning_texts,
    CampaignInfo, CampaignState, CampaignState as S, check_channel_allowed, ContentCreate, CreativeCreate,
    error, fail, from_validation, invalid, not_found, PlaceCreate, PromoContent, reject, SegmentsUpdate,
    TagCreate,
)


# --- Зависимости ---


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def require_role(role: str):
    """Подключается параметром эндпоинта: зависимости выполняются раньше разбора тела,
    поэтому ROLE_FORBIDDEN возвращается первым (task.md §2.3)."""

    def dependency(x_user: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> str:
        if x_role != role or not x_user:
            fail("ROLE_FORBIDDEN", detail=f"нужна роль {role}")
        return x_user

    return dependency


def parse(model: type[BaseModel], body: dict):
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise ApiError(from_validation(exc)) from exc


# --- Жизненный цикл (§2.3) ---


MANAGER = "campaignManager"
MODERATOR = "campaignModerator"

EDITABLE = {S.DRAFT, S.NEEDS_WORK, S.APPROVED, S.ACTIVE, S.ACTIVE_EDITING}
TO_MODERATION_FROM = {S.DRAFT, S.NEEDS_WORK, S.ACTIVE_EDITING}
DELETABLE = {S.DRAFT, S.NEEDS_WORK}


def state_after_edit(state: str) -> str:
    """Правка снимает одобрение, а правка живой кампании переводит её в ACTIVE_EDITING."""
    if state == S.APPROVED:
        return S.DRAFT
    if state in (S.ACTIVE, S.ACTIVE_EDITING):
        return S.ACTIVE_EDITING
    return state


# --- Ответы ---


HEADER_FIELDS = (
    "id", "name", "marketingName", "startDate", "startTime", "endDate", "endTime", "topic", "tags",
    "keywords", "state", "published", "audienceType", "weight", "initialCtr", "author", "lastEditAuthor",
    "places",
)
LIST_FIELDS = ("id", "name", "state", "published", "topic", "startDate", "startTime", "endDate", "endTime")
STATUS_FIELDS = ("id", "state", "published", "author")


def to_dict(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def pick(c: Campaign, fields: tuple[str, ...]) -> dict:
    return {field: getattr(c, field) for field in fields}


def details(s: Session, c: Campaign) -> dict:
    def children(model) -> list[dict]:
        return [to_dict(row) for row in s.scalars(select(model).where(model.campaignId == c.id))]

    return {
        **pick(c, HEADER_FIELDS),
        "banners": children(Banner),
        "contents": children(Content),
        "creatives": children(Creative),
        "segments": {"included": c.includedSegments, "excluded": c.excludedSegments},
    }


# --- Журнал аудита (§3) ---


def audit_diff(old: dict, new: dict) -> dict | None:
    changes = {
        key: {"from": old.get(key), "to": new.get(key)}
        for key in old.keys() | new.keys()
        if old.get(key) != new.get(key)
    }
    return changes or None


def audit_record(
    s: Session,
    campaign_id: int,
    entity: str,
    entity_id: int,
    action: str,
    actor: str,
    changes: dict | None = None,
    comment: str | None = None,
) -> None:
    s.add(AuditEntry(
        campaignId=campaign_id,
        entity=entity,
        entityId=entity_id,
        action=action,
        changes=changes,
        at=datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0),
        actor=actor,
        comment=comment,
    ))


def audit_dto(entry: AuditEntry) -> dict:
    return {
        "entity": entry.entity,
        "entityId": entry.entityId,
        "action": entry.action,
        "changes": entry.changes,
        "at": entry.at.isoformat(),
        "actor": entry.actor,
        "comment": entry.comment,
    }


def segment_errors(s: Session, included: list[str], excluded: list[str]) -> list[dict]:
    result = []
    for field, codes in (("included", included), ("excluded", excluded)):
        for code in codes:
            segment = s.get(Segment, code)
            if segment is None:
                result.append(invalid(f"Нет такого сегмента: {code}", field))
            elif segment.state != "ACTIVE":
                result.append(invalid(f"Сегмент {code} не активен, выбрать его нельзя", field))
    return result


# --- Валидация (§4) ---


def campaign_errors(s: Session, c: Campaign) -> list[dict]:
    errors = []
    if not c.places:
        errors.append(invalid("Не задано ни одного места показа", "places"))

    if c.audienceType == AudienceType.SEGMENTED and not c.includedSegments:
        errors.append(invalid("Нужен хотя бы один сегмент включения", "segments.included"))
    if c.audienceType == AudienceType.ALL_USERS and (c.includedSegments or c.excludedSegments):
        errors.append(error("SEGMENTS_FORBIDDEN_FOR_ALL_USERS", "segments"))
    errors += segment_errors(s, c.includedSegments, c.excludedSegments)

    banners = {b.id: b for b in s.scalars(select(Banner).where(Banner.campaignId == c.id))}
    for banner in banners.values():
        try:
            content = BannerContent.model_validate(banner.content)
        except ValidationError as exc:
            errors += from_validation(exc)
        else:
            errors += banner_limit_errors(content, to_dict(s.get(BannerType, banner.bannerTypeId)), f"banners.{banner.id}")

    for row in s.scalars(select(Content).where(Content.campaignId == c.id)):
        try:
            PromoContent.model_validate(row.content)
        except ValidationError as exc:
            errors += from_validation(exc)

    for creative in s.scalars(select(Creative).where(Creative.campaignId == c.id)):
        banner_type = s.get(BannerType, banners[creative.bannerId].bannerTypeId)
        if not check_channel_allowed(creative.channelCode, to_dict(banner_type)):
            errors.append(invalid(f"Канал {creative.channelCode} не разрешён для типа {banner_type.code}", f"creatives.{creative.id}"))

    return errors


def campaign_warnings(s: Session, c: Campaign) -> list[str]:
    places = [s.get(Place, place_id) for place_id in c.places]
    covered = set(s.scalars(
        select(BannerType.code)
        .join(Banner, Banner.bannerTypeId == BannerType.id)
        .join(Creative, Creative.bannerId == Banner.id)
        .where(Creative.campaignId == c.id)
    ))

    return campaign_warning_texts([to_dict(place) for place in places], covered, c.tags)


# --- Справочники ---


router = APIRouter()
manager = require_role(MANAGER)


def list_all(s: Session, model) -> list[dict]:
    return [to_dict(row) for row in s.scalars(select(model))]


def add_dictionary(path: str, model) -> None:
    def read(s: Session = Depends(get_session)):
        return list_all(s, model)

    router.get(path, name=path)(read)


for path, model in {
    "/topics": Topic, "/tags": Tag, "/channels": Channel, "/banner-types": BannerType,
    "/segment-types": SegmentType, "/segments": Segment, "/places": Place,
}.items():
    add_dictionary(path, model)


@router.post("/places", status_code=201)
def create_place(body: dict = Body(...), _: str = Depends(manager), s: Session = Depends(get_session)):
    data = parse(PlaceCreate, body)
    if s.scalar(select(Place).where(Place.code == data.code)):
        reject(f"Место показа с кодом {data.code} уже существует", "code")
    place = Place(code=data.code, description=data.description, state="ACTIVE")
    s.add(place)
    s.commit()
    return to_dict(place)


@router.post("/tags", status_code=201)
def create_tag(body: dict = Body(...), _: str = Depends(manager), s: Session = Depends(get_session)):
    data = parse(TagCreate, body)
    if s.scalar(select(Tag).where(Tag.name == data.name)):
        reject(f"Тег «{data.name}» уже существует", "name")
    tag = Tag(name=data.name)
    s.add(tag)
    s.commit()
    return to_dict(tag)


moderator = require_role(MODERATOR)


def get_campaign(s: Session, campaign_id: int) -> Campaign:
    campaign = s.get(Campaign, campaign_id)
    if campaign is None:
        not_found("campaignId", campaign_id)
    return campaign


def get_editable(s: Session, campaign_id: int) -> Campaign:
    campaign = get_campaign(s, campaign_id)
    if campaign.state not in EDITABLE:
        fail("UPDATE_NOT_ALLOWED", detail=f"state={campaign.state}")
    return campaign


def mark_edited(s: Session, c: Campaign, user: str) -> None:
    """Вызывается после любой правки кампании или её дочерних сущностей."""
    c.lastEditAuthor = user
    new_state = state_after_edit(c.state)
    if new_state != c.state:
        audit_record(s, c.id, "CAMPAIGN", c.id, "UPDATE", user, audit_diff({"state": c.state}, {"state": new_state}))
        c.state = new_state


def apply_info(s: Session, c: Campaign, info: CampaignInfo) -> None:
    """Полная замена шапки: POST и PUT отличаются только наличием id."""
    if s.get(Topic, info.topic.value) is None:
        reject(f"Нет такой тематики: {info.topic.value}", "topic")
    for tag in info.tags:
        if s.get(Tag, tag.value) is None:
            not_found("tags", tag.value)
    for place in info.places:
        if s.get(Place, place.value) is None:
            not_found("places", place.value)

    same_name = s.scalar(select(Campaign.id).where(Campaign.name == info.name))
    if same_name is not None and same_name != c.id:
        fail("NAME_DUPLICATE", "name", detail=info.name)

    c.name = info.name
    c.marketingName = info.marketingName
    c.startDate = info.startDate.isoformat()
    c.startTime = info.startTime
    c.endDate = info.endDate.isoformat() if info.endDate else None
    c.endTime = info.endTime
    c.topic = info.topic.value
    c.tags = [tag.value for tag in info.tags]
    c.keywords = info.keywords
    c.audienceType = info.audienceType.value
    c.weight = info.weight
    c.initialCtr = info.initialCtr
    c.places = [place.value for place in info.places]


@router.get("/campaigns")
def list_campaigns(s: Session = Depends(get_session)):
    return [pick(c, LIST_FIELDS) for c in s.scalars(select(Campaign).order_by(Campaign.id))]


@router.get("/campaigns/{campaign_id}")
def get_details(campaign_id: int, s: Session = Depends(get_session)):
    return details(s, get_campaign(s, campaign_id))


@router.post("/campaigns", status_code=201)
def create_campaign(body: dict = Body(...), user: str = Depends(manager), s: Session = Depends(get_session)):
    info = parse(CampaignInfo, body)
    campaign = Campaign(author=user, lastEditAuthor=user)
    apply_info(s, campaign, info)
    s.add(campaign)
    s.flush()
    audit_record(s, campaign.id, "CAMPAIGN", campaign.id, "CREATE", user)
    s.commit()
    return pick(campaign, STATUS_FIELDS)


@router.put("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: int, body: dict = Body(...), user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    info = parse(CampaignInfo, body)
    if info.audienceType == AudienceType.ALL_USERS and (campaign.includedSegments or campaign.excludedSegments):
        fail("SEGMENTS_FORBIDDEN_FOR_ALL_USERS", "audienceType", detail="сначала очистите сегменты")

    before = pick(campaign, HEADER_FIELDS)
    apply_info(s, campaign, info)
    audit_record(s, campaign.id, "CAMPAIGN", campaign.id, "UPDATE", user, audit_diff(before, pick(campaign, HEADER_FIELDS)))
    mark_edited(s, campaign, user)
    s.commit()
    return details(s, campaign)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, user: str = Depends(manager), s: Session = Depends(get_session)):
    campaign = get_campaign(s, campaign_id)
    if campaign.state not in DELETABLE or campaign.published:
        fail("DELETE_NOT_ALLOWED", detail=f"state={campaign.state}, published={campaign.published}")
    for model in (Creative, Banner, Content):
        s.execute(delete(model).where(model.campaignId == campaign_id))
    audit_record(s, campaign_id, "CAMPAIGN", campaign_id, "DELETE", user)
    s.delete(campaign)
    s.commit()


@router.put("/campaigns/{campaign_id}/segments")
def update_segments(
    campaign_id: int, body: dict = Body(...), user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    data = parse(SegmentsUpdate, body)
    if campaign.audienceType == AudienceType.ALL_USERS and (data.included or data.excluded):
        fail("SEGMENTS_FORBIDDEN_FOR_ALL_USERS", "segments")
    errors = segment_errors(s, data.included, data.excluded)
    if errors:
        raise ApiError(errors)

    before = {"included": campaign.includedSegments, "excluded": campaign.excludedSegments}
    campaign.includedSegments = data.included
    campaign.excludedSegments = data.excluded
    audit_record(s, campaign.id, "SEGMENTS", campaign.id, "UPDATE", user, audit_diff(before, data.model_dump()))
    mark_edited(s, campaign, user)
    s.commit()
    return data.model_dump()


@router.get("/campaigns/{campaign_id}/warnings")
def get_warnings(campaign_id: int, s: Session = Depends(get_session)):
    campaign = get_campaign(s, campaign_id)
    return {"errors": campaign_errors(s, campaign), "warnings": campaign_warnings(s, campaign)}


@router.get("/campaigns/{campaign_id}/audit")
def get_audit(campaign_id: int, s: Session = Depends(get_session)):
    get_campaign(s, campaign_id)
    entries = s.scalars(
        select(AuditEntry).where(AuditEntry.campaignId == campaign_id).order_by(AuditEntry.at, AuditEntry.id)
    )
    return [audit_dto(entry) for entry in entries]


def transition(s: Session, c: Campaign, action: str, user: str, state: str, comment: str | None = None) -> dict:
    c.state = state
    audit_record(s, c.id, "CAMPAIGN", c.id, action, user, comment=comment)
    s.commit()
    return pick(c, STATUS_FIELDS)


@router.post("/campaigns/{campaign_id}/to-moderation")
def to_moderation(campaign_id: int, user: str = Depends(manager), s: Session = Depends(get_session)):
    campaign = get_campaign(s, campaign_id)
    if campaign.state not in TO_MODERATION_FROM:
        fail("TO_MODERATION_NOT_ALLOWED", detail=f"state={campaign.state}")
    errors = campaign_errors(s, campaign)
    if errors:
        raise ApiError(errors)
    return transition(s, campaign, "TO_MODERATION", user, CampaignState.ON_MODERATION)


@router.post("/campaigns/{campaign_id}/decline")
def decline(
    campaign_id: int, body: dict | None = Body(default=None), user: str = Depends(moderator),
    s: Session = Depends(get_session),
):
    campaign = get_campaign(s, campaign_id)
    if campaign.state != CampaignState.ON_MODERATION:
        fail("DECLINE_NOT_ALLOWED", detail=f"state={campaign.state}")
    comment = (body or {}).get("comment")
    if not isinstance(comment, str) or not comment.strip():
        reject("Укажите причину отклонения", "comment")
    return transition(s, campaign, "DECLINE", user, CampaignState.NEEDS_WORK, comment)


@router.post("/campaigns/{campaign_id}/approve")
def approve(campaign_id: int, user: str = Depends(moderator), s: Session = Depends(get_session)):
    campaign = get_campaign(s, campaign_id)
    if campaign.state != CampaignState.ON_MODERATION:
        fail("APPROVE_NOT_ALLOWED", detail=f"state={campaign.state}")
    return transition(s, campaign, "APPROVE", user, CampaignState.APPROVED)


def cbro_export(campaign_id: int) -> dict:
    """Заглушка Content Broker: в MVP всегда успех (task.md §5)."""
    exported_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    return {"status": "OK", "exportedAt": exported_at.isoformat()}


@router.post("/mock/cbro/export")
def cbro_endpoint(body: dict = Body(...)):
    return cbro_export(body.get("campaignId"))


@router.post("/campaigns/{campaign_id}/activate")
def activate(campaign_id: int, user: str = Depends(manager), s: Session = Depends(get_session)):
    campaign = get_campaign(s, campaign_id)
    if campaign.state != CampaignState.APPROVED:
        fail("ACTIVATE_NOT_ALLOWED", detail=f"state={campaign.state}")
    cbro_export(campaign_id)
    campaign.published = True
    return transition(s, campaign, "ACTIVATE", user, CampaignState.ACTIVE)


@router.post("/campaigns/{campaign_id}/stop")
def stop(campaign_id: int, user: str = Depends(manager), s: Session = Depends(get_session)):
    campaign = get_campaign(s, campaign_id)
    if not campaign.published:
        fail("STOP_NOT_ALLOWED", detail=f"state={campaign.state}")
    campaign.published = False
    return transition(s, campaign, "STOP", user, CampaignState.STOPPED)




def get_child(s: Session, model, campaign_id: int, child_id: int, field: str):
    child = s.get(model, child_id)
    if child is None or child.campaignId != campaign_id:
        not_found(field, child_id)
    return child


def flat(row, body_key: str = "content") -> dict:
    """Плоский вид для diff: как в примере аудита, поля контента идут верхним уровнем."""
    data = to_dict(row)
    return {**{k: v for k, v in data.items() if k != body_key}, **data.get(body_key, {})}


def parse_banner(s: Session, body: dict) -> BannerCreate:
    data = parse(BannerCreate, body)
    banner_type = s.get(BannerType, data.bannerTypeId)
    if banner_type is None:
        not_found("bannerTypeId", data.bannerTypeId)
    errors = banner_limit_errors(data.content, to_dict(banner_type))
    if errors:
        raise ApiError(errors)
    return data


@router.post("/campaigns/{campaign_id}/banners", status_code=201)
def create_banner(
    campaign_id: int, body: dict = Body(...), user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    data = parse_banner(s, body)
    # В базу идёт исходный JSON: модель Pydantic нормализует url.
    banner = Banner(campaignId=campaign_id, name=data.name, bannerTypeId=data.bannerTypeId, content=body["content"])
    s.add(banner)
    s.flush()
    audit_record(s, campaign_id, "BANNER", banner.id, "CREATE", user)
    mark_edited(s, campaign, user)
    s.commit()
    return to_dict(banner)


@router.put("/campaigns/{campaign_id}/banners/{banner_id}")
def update_banner(
    campaign_id: int, banner_id: int, body: dict = Body(...), user: str = Depends(manager),
    s: Session = Depends(get_session),
):
    campaign = get_editable(s, campaign_id)
    banner = get_child(s, Banner, campaign_id, banner_id, "bannerId")
    data = parse_banner(s, body)
    before = flat(banner)
    banner.name = data.name
    banner.bannerTypeId = data.bannerTypeId
    banner.content = body["content"]
    audit_record(s, campaign_id, "BANNER", banner.id, "UPDATE", user, audit_diff(before, flat(banner)))
    mark_edited(s, campaign, user)
    s.commit()
    return to_dict(banner)


@router.delete("/campaigns/{campaign_id}/banners/{banner_id}", status_code=204)
def delete_banner(
    campaign_id: int, banner_id: int, user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    banner = get_child(s, Banner, campaign_id, banner_id, "bannerId")
    for creative in s.scalars(select(Creative).where(Creative.bannerId == banner_id)):
        audit_record(s, campaign_id, "CREATIVE", creative.id, "DELETE", user)
        s.delete(creative)
    s.flush()
    audit_record(s, campaign_id, "BANNER", banner.id, "DELETE", user)
    s.delete(banner)
    mark_edited(s, campaign, user)
    s.commit()


@router.post("/campaigns/{campaign_id}/contents", status_code=201)
def create_content(
    campaign_id: int, body: dict = Body(...), user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    data = parse(ContentCreate, body)
    content = Content(campaignId=campaign_id, name=data.name, contentType=data.contentType, content=body["content"])
    s.add(content)
    s.flush()
    audit_record(s, campaign_id, "CONTENT", content.id, "CREATE", user)
    mark_edited(s, campaign, user)
    s.commit()
    return to_dict(content)


@router.put("/campaigns/{campaign_id}/contents/{content_id}")
def update_content(
    campaign_id: int, content_id: int, body: dict = Body(...), user: str = Depends(manager),
    s: Session = Depends(get_session),
):
    campaign = get_editable(s, campaign_id)
    content = get_child(s, Content, campaign_id, content_id, "contentId")
    data = parse(ContentCreate, body)
    before = flat(content)
    content.name = data.name
    content.content = body["content"]
    audit_record(s, campaign_id, "CONTENT", content.id, "UPDATE", user, audit_diff(before, flat(content)))
    mark_edited(s, campaign, user)
    s.commit()
    return to_dict(content)


@router.delete("/campaigns/{campaign_id}/contents/{content_id}", status_code=204)
def delete_content(
    campaign_id: int, content_id: int, user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    content = get_child(s, Content, campaign_id, content_id, "contentId")
    for creative in s.scalars(select(Creative).where(Creative.contentId == content_id)):
        creative.contentId = None
        audit_record(
            s, campaign_id, "CREATIVE", creative.id, "UPDATE", user, audit_diff({"contentId": content_id}, {"contentId": None})
        )
    s.flush()
    audit_record(s, campaign_id, "CONTENT", content.id, "DELETE", user)
    s.delete(content)
    mark_edited(s, campaign, user)
    s.commit()


def check_creative(s: Session, campaign_id: int, data: CreativeCreate, creative_id: int | None = None) -> None:
    banner = get_child(s, Banner, campaign_id, data.bannerId, "bannerId")
    if data.contentId is not None:
        get_child(s, Content, campaign_id, data.contentId, "contentId")
    if s.scalar(select(Channel).where(Channel.code == data.channelCode)) is None:
        not_found("channelCode", data.channelCode)

    banner_type = s.get(BannerType, banner.bannerTypeId)
    if not check_channel_allowed(data.channelCode, to_dict(banner_type)):
        reject(f"Канал {data.channelCode} не разрешён для типа {banner_type.code}", "channelCode")

    same = s.scalar(select(Creative.id).where(
        Creative.campaignId == campaign_id,
        Creative.bannerId == data.bannerId,
        Creative.channelCode == data.channelCode,
    ))
    if same is not None and same != creative_id:
        reject(f"Креатив с баннером {data.bannerId} и каналом {data.channelCode} уже есть", "channelCode")


@router.post("/campaigns/{campaign_id}/creatives", status_code=201)
def create_creative(
    campaign_id: int, body: dict = Body(...), user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    data = parse(CreativeCreate, body)
    check_creative(s, campaign_id, data)
    creative = Creative(campaignId=campaign_id, **data.model_dump())
    s.add(creative)
    s.flush()
    audit_record(s, campaign_id, "CREATIVE", creative.id, "CREATE", user)
    mark_edited(s, campaign, user)
    s.commit()
    return to_dict(creative)


@router.put("/campaigns/{campaign_id}/creatives/{creative_id}")
def update_creative(
    campaign_id: int, creative_id: int, body: dict = Body(...), user: str = Depends(manager),
    s: Session = Depends(get_session),
):
    campaign = get_editable(s, campaign_id)
    creative = get_child(s, Creative, campaign_id, creative_id, "creativeId")
    data = parse(CreativeCreate, body)
    check_creative(s, campaign_id, data, creative_id)
    before = to_dict(creative)
    for field, value in data.model_dump().items():
        setattr(creative, field, value)
    audit_record(s, campaign_id, "CREATIVE", creative.id, "UPDATE", user, audit_diff(before, to_dict(creative)))
    mark_edited(s, campaign, user)
    s.commit()
    return to_dict(creative)


@router.delete("/campaigns/{campaign_id}/creatives/{creative_id}", status_code=204)
def delete_creative(
    campaign_id: int, creative_id: int, user: str = Depends(manager), s: Session = Depends(get_session)
):
    campaign = get_editable(s, campaign_id)
    creative = get_child(s, Creative, campaign_id, creative_id, "creativeId")
    audit_record(s, campaign_id, "CREATIVE", creative.id, "DELETE", user)
    s.delete(creative)
    mark_edited(s, campaign, user)
    s.commit()


# --- Приложение ---


def create_app(db_path: Path | str = DEFAULT_DB) -> FastAPI:
    is_new = not Path(db_path).exists()
    engine = make_engine(db_path)
    if is_new:
        seed(engine)

    app = FastAPI(title="Campaign Assistant API")
    app.state.engine = engine
    app.include_router(router)

    @app.exception_handler(ApiError)
    def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"errors": exc.errors}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    def request_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            invalid(item["msg"], ".".join(str(part) for part in item["loc"]))
            for item in exc.errors()
        ]
        return JSONResponse({"errors": errors}, status_code=400)

    @app.middleware("http")
    async def echo_user_headers(request: Request, call_next):
        response = await call_next(request)
        for header in ("X-User", "X-Role"):
            if header in request.headers:
                response.headers[header] = request.headers[header]
        return response

    return app
