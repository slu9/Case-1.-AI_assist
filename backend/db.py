"""Таблицы, чтение моков и наполнение БД: python -m backend.db [путь к .db]."""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, Engine, event, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


DATA = Path(__file__).resolve().parents[1] / "data"
MOCKS = DATA / "mocks"
MOCK_DATA = DATA / "mock-data.md"


def load(name: str):
    return json.loads((MOCKS / f"{name}.json").read_text(encoding="utf-8"))


def _markdown() -> str:
    return MOCK_DATA.read_text(encoding="utf-8")


def _topics() -> list[dict]:
    codes = re.search(r"TOPIC \(topics\.json\).*?`([A-Z_, ]+)`", _markdown()).group(1).split(", ")
    labels = {
        row["payload"]["topic"]["value"]: row["payload"]["topic"]["label"]
        for row in load("campaign_create_payloads")
    }
    return [{"value": code, "label": labels.get(code, code)} for code in codes]


def _tags() -> list[dict]:
    line = re.search(r"^TAG \(tags\.json\).*?: (.+?)\. Создание", _markdown(), re.M).group(1)
    return [{"id": int(id_), "name": name} for name, id_ in re.findall(r"\s*([^,(]+?)\((\d+)\)", line)]


def _segment_types() -> list[dict]:
    codes = re.search(r"Типы \(8\): `([A-Z_, ]+)`", _markdown()).group(1).split(", ")
    return [{"code": code, "name": code} for code in codes]


def _segments() -> list[dict]:
    rows = re.findall(
        r"^\| ([A-Z0-9_]+) \| ([^|]+?) \| ([A-Z_]+) \| (ACTIVE|NEW) \| ([\d ]+?) \|$", _markdown(), re.M
    )
    return [
        {"code": code, "name": name, "type": type_, "state": state, "count": int(count.replace(" ", ""))}
        for code, name, type_, state, count in rows
    ]


def _places() -> list[dict]:
    rows = re.findall(r"^\| (\d+) \| (\w+) \| ([^|]+?) \| (\w+) \| (ACTIVE|INACTIVE) \|$", _markdown(), re.M)
    return [
        {"id": int(id_), "code": code, "description": description, "defaultBanner": banner, "state": state}
        for id_, code, description, banner, state in rows
    ]


def _transition(campaign_id, action, day, actor, comment=None):
    """Время суток в документации не указано, поэтому у записей только дата."""
    return {
        "entity": "CAMPAIGN", "entityId": campaign_id, "action": action, "changes": None,
        "at": f"{day}T00:00:00", "actor": actor, "comment": comment,
    }


def _lifecycle_transitions() -> list[dict]:
    """Только переходы с датами из mock-data.md §3, §5, §6.5; по остальным кампаниям данных нет."""
    return [
        _transition(102, "CREATE", "2026-10-05", "ivanov.p"),
        _transition(102, "TO_MODERATION", "2026-10-06", "ivanov.p"),
        _transition(102, "DECLINE", "2026-10-07", "petrova.m", "Заголовок баннера не отражает суть акции"),
        _transition(102, "TO_MODERATION", "2026-10-08", "ivanov.p"),
        _transition(102, "APPROVE", "2026-10-09", "petrova.m"),
        _transition(102, "ACTIVATE", "2026-10-10", "ivanov.p"),
        _transition(104, "CREATE", "2026-10-20", "ivanov.p"),
        _transition(104, "TO_MODERATION", "2026-10-21", "ivanov.p"),
        _transition(
            104, "DECLINE", "2026-10-22", "petrova.m",
            "Креативы настроены не для всех мест показа; добавьте теги кампании",
        ),
        _transition(114, "STOP", "2026-10-26", "ivanov.p"),
    ]


FROM_DOCS = {
    "topics": _topics,
    "tags": _tags,
    "segment_types": _segment_types,
    "segments": _segments,
    "places": _places,
    "lifecycle_transitions": _lifecycle_transitions,
}


def dictionary(name: str):
    if (MOCKS / f"{name}.json").exists():
        return load(name)
    return FROM_DOCS[name]()


# --- Таблицы ---


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Topic(Base):
    __tablename__ = "topics"
    value: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str]


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str]


class BannerType(Base):
    __tablename__ = "banner_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str]
    previewForm: Mapped[str]
    titleMaxLength: Mapped[int]
    textMaxLength: Mapped[int]
    channels: Mapped[list[Any]]


class SegmentType(Base):
    __tablename__ = "segment_types"
    code: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]


class Segment(Base):
    __tablename__ = "segments"
    code: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    type: Mapped[str] = mapped_column(ForeignKey("segment_types.code"))
    state: Mapped[str]
    count: Mapped[int]


class Place(Base):
    __tablename__ = "places"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str]
    defaultBanner: Mapped[str | None]  # у созданных через POST /places не задаётся
    state: Mapped[str] = mapped_column(default="ACTIVE")


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    marketingName: Mapped[str | None]
    startDate: Mapped[str]
    startTime: Mapped[str]
    endDate: Mapped[str | None]
    endTime: Mapped[str | None]
    topic: Mapped[str] = mapped_column(ForeignKey("topics.value"))
    tags: Mapped[list[Any]] = mapped_column(default=list)
    keywords: Mapped[str | None]
    state: Mapped[str] = mapped_column(default="DRAFT")
    published: Mapped[bool] = mapped_column(default=False)
    audienceType: Mapped[str]
    weight: Mapped[float] = mapped_column(default=0.0)
    initialCtr: Mapped[float] = mapped_column(default=15.0)
    author: Mapped[str]
    lastEditAuthor: Mapped[str]
    places: Mapped[list[Any]] = mapped_column(default=list)
    includedSegments: Mapped[list[Any]] = mapped_column(default=list)
    excludedSegments: Mapped[list[Any]] = mapped_column(default=list)


class Banner(Base):
    __tablename__ = "banners"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaignId: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    name: Mapped[str]
    bannerTypeId: Mapped[int] = mapped_column(ForeignKey("banner_types.id"))
    content: Mapped[dict[str, Any]]


class Content(Base):
    __tablename__ = "contents"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaignId: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    name: Mapped[str]
    contentType: Mapped[str]
    content: Mapped[dict[str, Any]]


class Creative(Base):
    __tablename__ = "creatives"
    __table_args__ = (UniqueConstraint("campaignId", "bannerId", "channelCode"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaignId: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    name: Mapped[str]
    bannerId: Mapped[int] = mapped_column(ForeignKey("banners.id"))
    contentId: Mapped[int | None] = mapped_column(ForeignKey("contents.id"))
    channelCode: Mapped[str]


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaignId: Mapped[int] = mapped_column(index=True)  # без FK: журнал переживает удаление кампании
    entity: Mapped[str]
    entityId: Mapped[int]
    action: Mapped[str]
    changes: Mapped[dict[str, Any] | None]
    at: Mapped[datetime]
    actor: Mapped[str]
    comment: Mapped[str | None]


DEFAULT_DB = Path(os.environ.get("CAMPAIGN_DB_PATH", DATA.parent / "campaigns.db"))


# --- Наполнение моками ---


def make_engine(db_path: Path | str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    return engine


def seed(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    places_by_campaign = {r["campaignId"]: r["placeIds"] for r in load("campaign_places")}
    segments_by_campaign = {r["campaignId"]: r for r in load("campaign_segments")}

    with Session(engine) as s:
        s.add_all(Topic(**r) for r in dictionary("topics"))
        s.add_all(Tag(**r) for r in dictionary("tags"))
        s.add_all(Channel(**r) for r in load("channels"))
        s.add_all(BannerType(**r) for r in load("banner_types"))
        s.add_all(SegmentType(**r) for r in dictionary("segment_types"))
        s.flush()
        s.add_all(Segment(**r) for r in dictionary("segments"))
        s.add_all(Place(**r) for r in dictionary("places"))

        for row in load("campaigns"):
            segments = segments_by_campaign[row["id"]]
            s.add(Campaign(
                **row,
                places=places_by_campaign[row["id"]],
                includedSegments=segments["included"],
                excludedSegments=segments["excluded"],
            ))
        s.flush()

        s.add_all(Banner(**r) for r in load("campaign_banners"))
        s.add_all(Content(**r) for r in load("campaign_contents"))
        s.flush()
        s.add_all(Creative(**r) for r in load("campaign_creatives"))

        for row in dictionary("lifecycle_transitions"):
            s.add(AuditEntry(campaignId=row["entityId"], **{**row, "at": datetime.fromisoformat(row["at"])}))

        s.commit()


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    db_path.unlink(missing_ok=True)  # файл со старой схемой иначе ломает DROP TABLE
    seed(make_engine(db_path))
    print(f"БД готова: {db_path}")


if __name__ == "__main__":
    main()
