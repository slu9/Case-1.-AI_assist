import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api import create_app
from backend.db import (
    AuditEntry, Banner, BannerType, Campaign, Channel, Content, Creative, make_engine, Place, seed, Segment,
    SegmentType, Tag, Topic,
)
from backend.domain import (
    BannerContent, CampaignInfo, check_audience, check_banner_limits, check_channel_allowed, ContentCreate,
    PromoContent, SegmentsUpdate,
)


MOCKS = Path(__file__).resolve().parents[1] / "data" / "mocks"
MANAGER = {"X-User": "ivanov.p", "X-Role": "campaignManager"}
MODERATOR = {"X-User": "petrova.m", "X-Role": "campaignModerator"}

CAMPAIGN = {
    "name": "Вклад 16%",
    "startDate": "2026-11-05",
    "startTime": "00:00",
    "endDate": "2026-12-31",
    "endTime": "23:59",
    "topic": {"value": "SALES", "label": "Продажи"},
    "tags": [{"value": 5, "label": "Вклад"}],
    "audienceType": "SEGMENTED",
    "places": [{"value": 1, "label": "mainScreenStories"}],
}
BANNER = {"name": "Сторис", "bannerTypeId": 1, "content": {"title": "Вклад 16%", "actionType": "default"}}
CONTENT = {
    "name": "Промо",
    "contentType": "PROMO",
    "content": {"role": "promo", "component": {
        "role": "linearContainer", "axis": "v",
        "components": [{"role": "text", "format": "none", "text": "Ставка 16%"}],
    }},
}


def mock(name):
    return json.loads((MOCKS / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def api(tmp_path):
    return TestClient(create_app(tmp_path / "test.db"))


def codes(response):
    return [e["code"] for e in response.json()["errors"]]


def fields(response):
    return [e["field"] for e in response.json()["errors"]]


def state(api, campaign_id):
    return api.get(f"/campaigns/{campaign_id}").json()["state"]


def post(api, path, body=None, headers=MANAGER):
    return api.post(path, json=body, headers=headers)


def new_draft(api, **patch):
    response = post(api, "/campaigns", {**CAMPAIGN, **patch})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def build_ready(api):
    """Черновик, готовый к модерации, как в §9."""
    cid = new_draft(api)
    api.put(f"/campaigns/{cid}/segments", json={"included": ["AGE_26_45"], "excluded": []}, headers=MANAGER)
    banner = post(api, f"/campaigns/{cid}/banners", BANNER).json()["id"]
    content = post(api, f"/campaigns/{cid}/contents", CONTENT).json()["id"]
    post(api, f"/campaigns/{cid}/creatives", {
        "name": "Android", "bannerId": banner, "contentId": content, "channelCode": "ANDROID",
    })
    return cid


def test_dictionaries(api):
    sizes = {"topics": 11, "tags": 6, "channels": 3, "banner-types": 2, "segment-types": 8, "segments": 40, "places": 8}
    for path, size in sizes.items():
        assert len(api.get(f"/{path}").json()) == size


def test_list_and_details_shapes(api):
    item = api.get("/campaigns").json()[0]
    assert set(item) == {"id", "name", "state", "published", "topic", "startDate", "startTime", "endDate", "endTime"}
    details = api.get("/campaigns/101").json()
    assert (details["topic"], details["tags"], details["places"]) == ("SALES", [4, 3], [2])
    assert details["segments"] == {"included": ["CHANNEL_VIP", "CITY_MSK"], "excluded": ["EXC_UNSUBSCRIBED"]}
    assert [len(details[k]) for k in ("banners", "contents", "creatives")] == [1, 1, 2]


def test_user_headers_are_echoed(api):
    response = api.get("/topics", headers=MANAGER)
    assert response.headers["X-User"] == "ivanov.p"
    assert response.headers["X-Role"] == "campaignManager"


def test_warnings_match_mock_oracle(api):
    expected = {row["campaignId"]: row["warnings"] for row in mock("campaign_warnings")}
    for campaign in api.get("/campaigns").json():
        body = api.get(f"/campaigns/{campaign['id']}/warnings").json()
        assert body["errors"] == []
        assert sorted(body["warnings"]) == sorted(expected.get(campaign["id"], []))


def test_scenario_from_section_9(api):
    cid = build_ready(api)
    assert api.get(f"/campaigns/{cid}/warnings").json() == {"errors": [], "warnings": []}
    response = post(api, f"/campaigns/{cid}/to-moderation")
    assert response.json() == {"id": cid, "state": "ON_MODERATION", "published": False, "author": "ivanov.p"}
    actions = [e["action"] for e in api.get(f"/campaigns/{cid}/audit").json()]
    assert actions[0] == "CREATE"
    assert actions[-1] == "TO_MODERATION"


def test_full_cycle_with_live_edit(api):
    cid = build_ready(api)
    post(api, f"/campaigns/{cid}/to-moderation")
    post(api, f"/campaigns/{cid}/approve", headers=MODERATOR)
    response = post(api, f"/campaigns/{cid}/activate")
    assert (response.json()["state"], response.json()["published"]) == ("ACTIVE", True)

    # Правка живой кампании не останавливает показ.
    post(api, f"/campaigns/{cid}/banners", BANNER)
    details = api.get(f"/campaigns/{cid}").json()
    assert (details["state"], details["published"]) == ("ACTIVE_EDITING", True)

    post(api, f"/campaigns/{cid}/to-moderation")
    post(api, f"/campaigns/{cid}/approve", headers=MODERATOR)
    assert api.get(f"/campaigns/{cid}").json()["published"] is True
    post(api, f"/campaigns/{cid}/activate")

    response = post(api, f"/campaigns/{cid}/stop")
    assert (response.json()["state"], response.json()["published"]) == ("STOPPED", False)
    assert codes(post(api, f"/campaigns/{cid}/banners", BANNER)) == ["UPDATE_NOT_ALLOWED"]


def test_fix_loop_on_campaign_104(api):
    declines = [e for e in api.get("/campaigns/104/audit").json() if e["action"] == "DECLINE"]
    assert "добавьте теги" in declines[0]["comment"]

    banner = post(api, "/campaigns/104/banners", BANNER).json()["id"]
    post(api, "/campaigns/104/creatives", {"name": "Сторис", "bannerId": banner, "channelCode": "iOS"})
    payload = {
        "name": "Ипотека: ставка 4,9%", "startDate": "2026-11-01", "startTime": "00:00",
        "endDate": "2026-12-15", "endTime": "23:59", "topic": {"value": "SALES", "label": "Продажи"},
        "tags": [{"value": 1, "label": "Банковские продукты"}], "audienceType": "SEGMENTED",
        "places": [{"value": 1, "label": "mainScreenStories"}],
    }
    assert api.put("/campaigns/104", json=payload, headers=MANAGER).status_code == 200
    assert state(api, 104) == "NEEDS_WORK"
    assert api.get("/campaigns/104/warnings").json()["warnings"] == []
    assert post(api, "/campaigns/104/to-moderation").json()["state"] == "ON_MODERATION"


@pytest.mark.parametrize("campaign_id, path, headers, code", [
    (101, "approve", MODERATOR, "APPROVE_NOT_ALLOWED"),
    (101, "decline", MODERATOR, "DECLINE_NOT_ALLOWED"),
    (101, "activate", MANAGER, "ACTIVATE_NOT_ALLOWED"),
    (101, "stop", MANAGER, "STOP_NOT_ALLOWED"),
    (102, "to-moderation", MANAGER, "TO_MODERATION_NOT_ALLOWED"),
    (103, "to-moderation", MANAGER, "TO_MODERATION_NOT_ALLOWED"),
    (114, "stop", MANAGER, "STOP_NOT_ALLOWED"),
])
def test_forbidden_transitions(api, campaign_id, path, headers, code):
    response = post(api, f"/campaigns/{campaign_id}/{path}", {"comment": "x"}, headers)
    assert response.status_code == 400
    assert codes(response) == [code]


@pytest.mark.parametrize("path, headers", [
    ("approve", MANAGER),
    ("decline", MANAGER),
    ("activate", MODERATOR),
    ("stop", MODERATOR),
    ("to-moderation", MODERATOR),
    ("to-moderation", {}),
])
def test_role_is_checked_before_state(api, path, headers):
    assert codes(post(api, f"/campaigns/114/{path}", {}, headers)) == ["ROLE_FORBIDDEN"]


def test_role_is_checked_before_body_and_existence(api):
    assert codes(post(api, "/campaigns/999999/banners", {}, MODERATOR)) == ["ROLE_FORBIDDEN"]


def test_moderator_cannot_create(api):
    assert codes(post(api, "/campaigns", CAMPAIGN, MODERATOR)) == ["ROLE_FORBIDDEN"]
    assert codes(post(api, "/tags", {"name": "x"}, MODERATOR)) == ["ROLE_FORBIDDEN"]


def test_decline_needs_comment_and_lands_in_audit(api):
    assert codes(post(api, "/campaigns/103/decline", {"comment": "  "}, MODERATOR)) == ["VALIDATION_ERROR"]
    assert codes(post(api, "/campaigns/103/decline", None, MODERATOR)) == ["VALIDATION_ERROR"]
    assert post(api, "/campaigns/103/decline", {"comment": "Нет условий"}, MODERATOR).json()["state"] == "NEEDS_WORK"
    assert api.get("/campaigns/103/audit").json()[-1]["comment"] == "Нет условий"


@pytest.mark.parametrize("campaign_id", [103, 110, 114])
def test_edit_forbidden_on_moderation_and_stopped(api, campaign_id):
    assert codes(post(api, f"/campaigns/{campaign_id}/banners", BANNER)) == ["UPDATE_NOT_ALLOWED"]


@pytest.mark.parametrize("method_path", [
    ("post", "banners"), ("post", "contents"),
])
def test_child_edit_of_approved_drops_approval(api, method_path):
    _, path = method_path
    body = BANNER if path == "banners" else CONTENT
    post(api, f"/campaigns/107/{path}", body)
    assert state(api, 107) == "DRAFT"
    entries = api.get("/campaigns/107/audit").json()
    assert entries[-1]["changes"] == {"state": {"from": "APPROVED", "to": "DRAFT"}}


def test_delete_rules(api):
    assert api.delete("/campaigns/101", headers=MANAGER).status_code == 204
    assert api.get("/campaigns/101").status_code == 404
    for campaign_id in (102, 103, 107, 114):
        assert codes(api.delete(f"/campaigns/{campaign_id}", headers=MANAGER)) == ["DELETE_NOT_ALLOWED"]


def test_live_campaign_in_needs_work_cannot_be_deleted(api):
    post(api, "/campaigns/109/to-moderation")
    post(api, "/campaigns/109/decline", {"comment": "Нет"}, MODERATOR)
    assert state(api, 109) == "NEEDS_WORK"
    assert codes(api.delete("/campaigns/109", headers=MANAGER)) == ["DELETE_NOT_ALLOWED"]


def test_campaign_validation_codes(api):
    assert fields(post(api, "/campaigns", {**CAMPAIGN, "name": ""})) == ["name"]
    assert fields(post(api, "/campaigns", {**CAMPAIGN, "name": "я" * 101})) == ["name"]
    assert codes(post(api, "/campaigns", {**CAMPAIGN, "name": "Сомелье: подбор вина"})) == ["NAME_DUPLICATE"]
    assert fields(post(api, "/campaigns", {**CAMPAIGN, "startTime": "9:00"})) == ["startTime"]
    assert "DATE_RANGE_INVALID" in codes(post(api, "/campaigns", {**CAMPAIGN, "endDate": "2026-11-01"}))
    assert codes(post(api, "/campaigns", {**CAMPAIGN, "topic": {"value": "NOPE", "label": "?"}})) == ["VALIDATION_ERROR"]
    response = post(api, "/campaigns", {**CAMPAIGN, "tags": [{"value": 999, "label": "?"}]})
    assert (response.status_code, codes(response)) == (404, ["ENTITY_NOT_FOUND"])


def test_put_with_own_name_is_not_a_duplicate(api):
    cid = new_draft(api)
    assert api.put(f"/campaigns/{cid}", json=CAMPAIGN, headers=MANAGER).status_code == 200


def test_error_body_shape(api):
    error = post(api, "/campaigns", {**CAMPAIGN, "name": "Сомелье: подбор вина"}).json()["errors"][0]
    assert set(error) == {"code", "message", "field"}
    assert error["field"] == "name"


def test_audience_rules(api):
    assert codes(post(api, "/campaigns/102/to-moderation")) == ["TO_MODERATION_NOT_ALLOWED"]

    cid = new_draft(api)
    assert codes(post(api, f"/campaigns/{cid}/to-moderation")) == ["VALIDATION_ERROR"]

    segments = f"/campaigns/{cid}/segments"
    assert codes(api.put(segments, json={"included": ["NOPE"]}, headers=MANAGER)) == ["VALIDATION_ERROR"]
    assert codes(api.put(segments, json={"included": ["SEG_DRAFT_WINTER"]}, headers=MANAGER)) == ["VALIDATION_ERROR"]

    api.put(segments, json={"included": ["CITY_MSK"]}, headers=MANAGER)
    to_all = api.put(f"/campaigns/{cid}", json={**CAMPAIGN, "audienceType": "ALL_USERS"}, headers=MANAGER)
    assert codes(to_all) == ["SEGMENTS_FORBIDDEN_FOR_ALL_USERS"]

    api.put(segments, json={"included": [], "excluded": []}, headers=MANAGER)
    assert api.put(f"/campaigns/{cid}", json={**CAMPAIGN, "audienceType": "ALL_USERS"}, headers=MANAGER).status_code == 200
    assert codes(api.put(segments, json={"included": ["CITY_MSK"]}, headers=MANAGER)) == ["SEGMENTS_FORBIDDEN_FOR_ALL_USERS"]


def test_places_are_required_for_moderation(api):
    cid = new_draft(api, audienceType="ALL_USERS", places=[])
    assert codes(post(api, f"/campaigns/{cid}/to-moderation")) == ["VALIDATION_ERROR"]


def test_no_creatives_only_warns(api):
    cid = new_draft(api, audienceType="ALL_USERS")
    assert api.get(f"/campaigns/{cid}/warnings").json()["warnings"] == ["Не для всех мест показа настроены креативы"]
    assert post(api, f"/campaigns/{cid}/to-moderation").status_code == 200


def assert_invalid(response, fragment):
    error = response.json()["errors"][0]
    assert error["code"] == "VALIDATION_ERROR"
    assert fragment in f"{error['field']} {error['message']}"


@pytest.mark.parametrize("content, fragment", [
    ({"actionType": "externalLink"}, "link обязателен"),
    ({"actionType": "doneCampaign", "link": {"web": "https://x"}}, "link запрещён"),
    ({"actionType": "default", "background": {"color": "#FFFFFF"}}, "background.color"),
    ({"actionType": "default", "title": "я" * 101}, "content.title"),
    ({"actionType": "default", "text": "я" * 501}, "content.text"),
])
def test_banner_errors(api, content, fragment):
    assert_invalid(post(api, "/campaigns/101/banners", {**BANNER, "content": content}), fragment)


def test_title_limit_message_explains_numbers(api):
    response = post(api, "/campaigns/101/banners", {**BANNER, "content": {"actionType": "default", "title": "я" * 132}})
    assert "132" in response.json()["errors"][0]["message"]
    assert "100" in response.json()["errors"][0]["message"]


def test_unknown_banner_type_is_404(api):
    response = post(api, "/campaigns/101/banners", {**BANNER, "bannerTypeId": 9})
    assert (response.status_code, codes(response)) == (404, ["ENTITY_NOT_FOUND"])


@pytest.mark.parametrize("component, fragment", [
    ({"role": "text", "text": "x"}, "text.format"),
    ({"role": "image"}, "image.url"),
    ({"role": "button", "text": "x", "actionType": "externalLink"}, "link обязателен"),
    ({"role": "button", "text": "x", "actionType": "closeCampaign", "link": {"web": "https://x"}}, "link запрещён"),
    ({"role": "video"}, "video"),
])
def test_content_errors(api, component, fragment):
    body = json.loads(json.dumps(CONTENT))
    body["content"]["component"]["components"] = [component]
    assert_invalid(post(api, "/campaigns/101/contents", body), fragment)


def test_creative_rules(api):
    cid = new_draft(api)
    story = post(api, f"/campaigns/{cid}/banners", BANNER).json()["id"]
    url = f"/campaigns/{cid}/creatives"

    assert codes(post(api, url, {"name": "c", "bannerId": story, "channelCode": "WEB"})) == ["VALIDATION_ERROR"]
    assert post(api, url, {"name": "c", "bannerId": story, "channelCode": "iOS"}).status_code == 201
    assert codes(post(api, url, {"name": "c", "bannerId": story, "channelCode": "iOS"})) == ["VALIDATION_ERROR"]

    missing_channel = post(api, url, {"name": "c", "bannerId": story, "channelCode": "ios"})
    assert (missing_channel.status_code, codes(missing_channel)) == (404, ["ENTITY_NOT_FOUND"])
    other_banner = post(api, url, {"name": "c", "bannerId": 201, "channelCode": "iOS"})
    assert (other_banner.status_code, codes(other_banner)) == (404, ["ENTITY_NOT_FOUND"])


def test_child_update_is_full_replace_with_diff(api):
    payload = {**BANNER, "bannerTypeId": 2, "content": {"title": "Новый", "actionType": "default"}}
    assert api.put("/campaigns/101/banners/201", json=payload, headers=MANAGER).status_code == 200
    banner = api.get("/campaigns/101").json()["banners"][0]
    assert banner["content"] == payload["content"]
    last = api.get("/campaigns/101/audit").json()[-1]
    assert last["entity"] == "BANNER"
    assert last["changes"]["title"]["to"] == "Новый"


def test_delete_banner_removes_its_creatives(api):
    assert api.delete("/campaigns/101/banners/201", headers=MANAGER).status_code == 204
    assert api.get("/campaigns/101").json()["creatives"] == []


def test_delete_content_detaches_it(api):
    assert api.delete("/campaigns/101/contents/301", headers=MANAGER).status_code == 204
    assert [c["contentId"] for c in api.get("/campaigns/101").json()["creatives"]] == [None, None]


def test_child_of_other_campaign_is_404(api):
    assert api.delete("/campaigns/102/banners/201", headers=MANAGER).status_code == 404


def test_create_place_and_tag_and_attach(api):
    place = post(api, "/places", {"code": "newPlace", "description": "Новое место"})
    assert (place.status_code, place.json()["state"], place.json()["defaultBanner"]) == (201, "ACTIVE", None)
    tag = post(api, "/tags", {"name": "Ипотека"}).json()
    assert codes(post(api, "/places", {"code": "newPlace", "description": "x"})) == ["VALIDATION_ERROR"]
    assert codes(post(api, "/tags", {"name": "Ипотека"})) == ["VALIDATION_ERROR"]
    assert codes(post(api, "/places", {"code": "x"})) == ["VALIDATION_ERROR"]

    cid = new_draft(
        api,
        audienceType="ALL_USERS",
        tags=[{"value": tag["id"], "label": "Ипотека"}],
        places=[{"value": place.json()["id"], "label": "newPlace"}],
    )
    # Для мест без defaultBanner правило покрытия не применяется.
    assert api.get(f"/campaigns/{cid}/warnings").json()["warnings"] == []


def test_audit_diff_records_actor(api):
    api.put("/campaigns/101", json={**CAMPAIGN, "name": "Новое имя"}, headers=MANAGER)
    entry = api.get("/campaigns/101/audit").json()[-1]
    assert entry["actor"] == "ivanov.p"
    assert entry["changes"]["name"] == {"from": "Премиальная карта: осенняя акция", "to": "Новое имя"}
    assert api.get("/campaigns/101").json()["lastEditAuthor"] == "ivanov.p"


def test_malformed_requests_use_common_error_body(api):
    response = api.post("/campaigns", content="{broken", headers={**MANAGER, "Content-Type": "application/json"})
    assert (response.status_code, codes(response)) == (400, ["VALIDATION_ERROR"])
    assert codes(api.get("/campaigns/abc")) == ["VALIDATION_ERROR"]


MOCKS = Path(__file__).resolve().parents[1] / "data" / "mocks"
STORY = {"titleMaxLength": 100, "textMaxLength": 500, "channels": ["iOS", "ANDROID"]}
SMART = {"titleMaxLength": 250, "textMaxLength": 1000, "channels": ["iOS", "ANDROID", "WEB"]}




LINK = {"iOS": "mobilebank://x"}
PROMO = {
    "role": "promo",
    "component": {
        "role": "linearContainer",
        "axis": "v",
        "components": [{"role": "text", "format": "none", "text": "Привет"}],
    },
}


def promo_with(component=None, **container):
    data = copy.deepcopy(PROMO)
    data["component"].update(container)
    if component:
        data["component"]["components"] = [component]
    return data


def test_all_mock_banners_are_valid():
    for row in mock("campaign_banners"):
        BannerContent.model_validate(row["content"])


def test_all_mock_contents_are_valid():
    for row in mock("campaign_contents"):
        ContentCreate.model_validate({k: row[k] for k in ("name", "contentType", "content")})


def test_all_mock_create_payloads_are_valid():
    for row in mock("campaign_create_payloads"):
        CampaignInfo.model_validate(row["payload"])


def test_minimal_banner():
    BannerContent.model_validate({"actionType": "default"})


@pytest.mark.parametrize("bad", [
    {},  # нет actionType
    {"actionType": "openLink"},
    {"actionType": "externalLink"},  # link обязателен
    {"actionType": "openSmartLink"},
    {"actionType": "closeCampaign", "link": LINK},  # link запрещён
    {"actionType": "doneCampaign", "link": LINK},
    {"actionType": "externalLink", "link": {}},  # пустой link
    {"actionType": "default", "background": {"color": "#FFFFFF"}},  # 6 знаков вместо 8
    {"actionType": "default", "titleStyle": {"fontSize": 9}},
    {"actionType": "default", "titleStyle": {"fontSize": 41}},
    {"actionType": "default", "textStyle": {"fontWeight": "heavy"}},
    {"actionType": "default", "image": {"url": "http://example.com/a.png"}},
    {"actionType": "default", "voiceOver": "я" * 201},
    {"actionType": "default", "subtitle": "лишнее поле"},
])
def test_invalid_banner_is_rejected(bad):
    with pytest.raises(ValidationError):
        BannerContent.model_validate(bad)


def test_banner_limits_depend_on_type():
    content = BannerContent(title="я" * 132, actionType="default")
    assert check_banner_limits(content, STORY) == ["title"]
    assert check_banner_limits(content, SMART) == []


@pytest.mark.parametrize("bad", [
    promo_with(axis="h"),
    promo_with(components=[]),
    promo_with(components=PROMO["component"]["components"] * 7),
    promo_with({"role": "text", "text": "без format"}),
    promo_with({"role": "text", "format": "markdown", "text": "x"}),
    promo_with({"role": "image"}),
    promo_with({"role": "video", "url": "https://x"}),
    promo_with({"role": "button", "text": "x", "actionType": "externalLink"}),
    promo_with({"role": "button", "text": "x", "actionType": "doneCampaign", "link": LINK}),
])
def test_invalid_promo_is_rejected(bad):
    with pytest.raises(ValidationError):
        PromoContent.model_validate(bad)


def test_story_is_not_allowed_on_web():
    assert not check_channel_allowed("WEB", STORY)
    assert check_channel_allowed("WEB", SMART)
    assert not check_channel_allowed("android", SMART)  # коды регистрозависимы


BASE_CAMPAIGN = {
    "name": "Тест",
    "startDate": "2026-11-05",
    "startTime": "10:00",
    "topic": {"value": "SALES", "label": "Продажи"},
    "audienceType": "ALL_USERS",
}


def test_campaign_defaults():
    campaign = CampaignInfo.model_validate(BASE_CAMPAIGN)
    assert (campaign.weight, campaign.initialCtr) == (0.0, 15.0)


@pytest.mark.parametrize("patch", [
    {"name": ""},
    {"name": "я" * 101},
    {"startTime": "25:00"},
    {"startTime": "9:00"},
    {"endDate": "2026-11-05", "endTime": "10:00"},  # end == start
    {"endDate": "2026-11-04", "endTime": "23:59"},
    {"audienceType": "EVERYONE"},
    {"keywords": "я" * 513},
])
def test_invalid_campaign_is_rejected(patch):
    with pytest.raises(ValidationError):
        CampaignInfo.model_validate({**BASE_CAMPAIGN, **patch})


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    engine = make_engine(tmp_path_factory.mktemp("db") / "test.db")
    seed(engine)
    with Session(engine) as s:
        yield s


@pytest.mark.parametrize("model, expected", [
    (Topic, 11), (Tag, 6), (Channel, 3), (BannerType, 2), (SegmentType, 8), (Segment, 40),
    (Place, 8), (Campaign, 14), (Banner, 15), (Content, 10), (Creative, 15),
])
def test_row_counts(session, model, expected):
    assert session.scalar(select(func.count()).select_from(model)) == expected


def test_only_inactive_places_are_the_two_archived(session):
    assert set(session.scalars(select(Place.code).where(Place.state == "INACTIVE"))) == {
        "oldStoriesSlot", "oldCatalogSlot",
    }


def test_new_segment_has_zero_count(session):
    assert session.get(Segment, "SEG_DRAFT_WINTER").count == 0


def test_campaign_lists_keep_their_order(session):
    campaign = session.get(Campaign, 101)
    assert campaign.tags == [4, 3]
    assert campaign.places == [2]
    assert campaign.includedSegments == ["CHANNEL_VIP", "CITY_MSK"]


def test_published_only_on_live_campaigns(session):
    assert set(session.scalars(select(Campaign.id).where(Campaign.published))) == {102, 106, 109}


def test_moderator_comment_of_104_is_in_audit(session):
    entry = session.scalar(
        select(AuditEntry).where(AuditEntry.campaignId == 104, AuditEntry.action == "DECLINE")
    )
    assert entry.actor == "petrova.m"
    assert "добавьте теги" in entry.comment


def test_only_documented_values_are_seeded(session):
    assert session.get(Topic, "SALES").label == "Продажи"  # подпись из тел создания
    assert session.get(Topic, "EXTRA").label == "EXTRA"  # подписи нет в материалах
    assert session.get(SegmentType, "AGE").name == "AGE"
    assert session.get(Tag, 5).name == "Вклад"
    assert session.scalar(select(func.count()).select_from(AuditEntry).where(AuditEntry.campaignId == 115)) == 0


def test_seed_is_repeatable(tmp_path):
    engine = make_engine(tmp_path / "again.db")
    seed(engine)
    seed(engine)
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Campaign)) == 14


MOCKS = Path(__file__).resolve().parents[1] / "data" / "mocks"


def advisories(included, excluded=()):
    return [a.code for a in check_audience(list(included), list(excluded))]


def test_young_and_old_together_is_advice_not_error():
    SegmentsUpdate(included=["AGE_18_25", "AGE_60_PLUS"])  # схема такую аудиторию пропускает
    assert advisories(["AGE_18_25", "AGE_60_PLUS"]) == ["AGE_GROUPS_NOT_ADJACENT"]


@pytest.mark.parametrize("included", [
    ["AGE_26_45"],
    ["AGE_18_25", "AGE_26_45"],
    ["AGE_60_PLUS", "AGE_46_60"],
    ["AGE_18_25", "AGE_26_45", "AGE_46_60", "AGE_60_PLUS"],
    ["AGE_26_45", "CITY_MSK"],
    [],
])
def test_adjacent_ages_get_no_advice(included):
    assert advisories(included) == []


def test_gap_in_the_middle_is_detected():
    assert advisories(["AGE_18_25", "AGE_46_60"]) == ["AGE_GROUPS_NOT_ADJACENT"]


def test_same_segment_included_and_excluded():
    assert advisories(["CITY_MSK", "AGE_26_45"], ["CITY_MSK"]) == ["SEGMENT_INCLUDED_AND_EXCLUDED"]


def test_mock_campaigns_get_no_advice():
    rows = json.loads((MOCKS / "campaign_segments.json").read_text(encoding="utf-8"))
    assert [r["campaignId"] for r in rows if advisories(r["included"], r["excluded"])] == []
