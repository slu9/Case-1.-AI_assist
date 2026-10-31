import base64
import json
import re
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from gigachat.exceptions import RateLimitError
from gigachat.models import ChatCompletion, Messages, MessagesRole

from backend.agent import Agent, Journal, Session, TOOL_DEFINITIONS
from backend.api import create_app as create_backend
from backend.llm import (
    GigaChatLLM, IMAGE_PROMPT, LLMError, LLMResponse, parse_response, plain_schema, to_function, to_gigachat,
    ToolCall,
)
from backend.server import create_app
from backend.tools import (
    lifecycle_facts,
    API_TOOLS, Backend, BackendError, Dictionaries, Draft, suggest_weight, TOOLS, wrap_refs,
)


MANAGER = ("ivanov.p", "campaignManager")
MODERATOR = ("petrova.m", "campaignModerator")

CAMPAIGN = {
    "name": "Вклад 16%", "startDate": "2026-11-05", "startTime": "00:00", "endDate": "2026-12-31", "endTime": "23:59",
    "topic": "SALES", "tags": [5], "audienceType": "SEGMENTED", "places": [1],
}
BANNER = {"key": "story", "name": "Сторис", "bannerTypeId": 1, "content": {"title": "Вклад", "actionType": "default"}}
CONTENT = {
    "key": "promo", "name": "Промо", "contentType": "PROMO",
    "content": {"role": "promo", "component": {
        "role": "linearContainer", "axis": "v",
        "components": [{"role": "text", "format": "none", "text": "Высокая ставка"}],
    }},
}
CREATIVES = {"creatives": [
    {"name": "Android", "bannerKey": "story", "contentKey": "promo", "channelCode": "ANDROID"},
    {"name": "iOS", "bannerKey": "story", "contentKey": "promo", "channelCode": "iOS"},
]}


class ScriptedLLM:
    """Отдаёт заранее заданные ходы и запоминает, что ему передали."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []

    def complete(self, system, context, messages, tools):
        self.seen.append(list(messages))
        self.tools = tools
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        if isinstance(turn, str):
            return LLMResponse(turn, raw=[])
        if isinstance(turn, LLMResponse):
            return turn
        calls = [ToolCall(f"call_{len(self.seen)}_{i}", name, data) for i, (name, data) in enumerate(turn)]
        return LLMResponse("", calls, "tool_use", raw=[])


def calls(*pairs):
    return list(pairs)


@pytest.fixture
def http(tmp_path):
    return TestClient(create_backend(tmp_path / "test.db"))


@pytest.fixture
def make(http, tmp_path):
    def factory(*turns, who=MANAGER):
        llm = ScriptedLLM(*turns)
        return Agent(llm, Backend(http), Journal(tmp_path / "journal.jsonl")), Session(*who), llm
    return factory


def last_results(session):
    return next(m for m in reversed(session.messages) if m["role"] == "tool")["results"]


def fill_draft():
    return calls(
        ("draft_update_campaign", CAMPAIGN),
        ("draft_set_segments", {"included": ["AGE_26_45", "CITY_MSK"], "excluded": ["EXC_UNSUBSCRIBED"]}),
        ("draft_upsert_banner", BANNER),
        ("draft_upsert_content", CONTENT),
        ("draft_set_creatives", CREATIVES),
        ("draft_review", {}),
    )


def campaign_count(http):
    return len(http.get("/campaigns").json())


def test_every_api_operation_has_a_tool(http):
    routes = {
        (method.upper(), path.replace("campaign_id", "campaignId").replace("banner_id", "bannerId")
         .replace("content_id", "contentId").replace("creative_id", "creativeId"))
        for path, ops in http.get("/openapi.json").json()["paths"].items()
        for method in ops if not path.startswith("/mock")
    }
    assert {(t.method, t.path) for t in API_TOOLS} == routes
    assert len(API_TOOLS) == 31


def test_all_writes_are_gated():
    for tool in API_TOOLS:
        assert tool.write == (tool.method != "GET"), tool.name
    assert TOOLS["apply_draft"].write


def test_role_is_never_a_tool_parameter():
    for definition in TOOL_DEFINITIONS:
        assert not {"role", "user", "actor"} & set(definition["input_schema"]["properties"]), definition["name"]


def test_tool_definitions_are_valid_for_the_api():
    assert len({d["name"] for d in TOOL_DEFINITIONS}) == len(TOOL_DEFINITIONS)
    for definition in TOOL_DEFINITIONS:
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", definition["name"])
        assert definition["description"]
        assert definition["input_schema"]["type"] == "object"
        assert set(definition["input_schema"].get("required", [])) <= set(definition["input_schema"]["properties"])
        json.dumps(definition)


def test_write_does_not_run_without_confirmation(http, make):
    before = campaign_count(http)
    agent, session, _ = make(fill_draft(), calls(("apply_draft", {})))
    turn = agent.send(session, "Кампания по вкладу")
    assert turn.confirmation[0]["tool"] == "apply_draft"
    assert campaign_count(http) == before


def test_scenario_from_section_9(http, make):
    agent, session, _ = make(
        fill_draft(), "Вот сводка", calls(("apply_draft", {})), "Кампания собрана",
        calls(("to_moderation", {"campaignId": 0})), "Ушла на модерацию",
    )
    assert agent.send(session, "Бриф").text == "Вот сводка"
    review = last_results(session)[-1]["content"]
    assert review["ready"] is True
    assert review["warnings"] == []
    assert "ЛЮБОЙ" in review["audience"]["semantics"]

    assert agent.send(session, "Да").confirmation
    assert agent.decide(session, True).text == "Кампания собрана"

    cid = session.draft.campaign_id
    campaign = http.get(f"/campaigns/{cid}").json()
    assert (campaign["state"], campaign["author"]) == ("DRAFT", "ivanov.p")
    assert campaign["segments"]["included"] == ["AGE_26_45", "CITY_MSK"]
    assert [len(campaign[k]) for k in ("banners", "contents", "creatives")] == [1, 1, 2]

    agent.llm.turns[0][0] = ("to_moderation", {"campaignId": cid})
    assert agent.send(session, "Отправляй").confirmation
    assert agent.decide(session, True).text == "Ушла на модерацию"
    assert http.get(f"/campaigns/{cid}").json()["state"] == "ON_MODERATION"


def test_rejection_tells_the_model_and_changes_nothing(http, make):
    before = campaign_count(http)
    agent, session, llm = make(fill_draft(), calls(("apply_draft", {})), "Что поменять?")
    agent.send(session, "Бриф")
    assert agent.decide(session, False, "Другое название").text == "Что поменять?"
    assert campaign_count(http) == before
    outcome = last_results(session)[0]
    assert outcome["is_error"] and "Другое название" in outcome["content"]["reason"]


def test_new_message_while_pending_answers_every_call(http, make):
    before = campaign_count(http)
    agent, session, llm = make(fill_draft(), calls(("apply_draft", {})), "Понял")
    agent.send(session, "Бриф")
    assert agent.send(session, "Подожди, поменяй дату").text == "Понял"
    message = session.messages[-2]
    assert (message["role"], message["text"]) == ("tool", "Подожди, поменяй дату")
    assert message["results"][0]["is_error"]
    assert session.pending is None
    assert campaign_count(http) == before


def test_mixed_turn_keeps_results_in_call_order(http, make):
    agent, session, _ = make(
        calls(("get_topics", {}), ("create_tag", {"name": "Ипотека"}), ("get_channels", {})), "Готово",
    )
    assert [a["tool"] for a in agent.send(session, "x").confirmation] == ["create_tag"]
    agent.decide(session, True)
    results = last_results(session)
    assert [r["is_error"] for r in results] == [False, False, False]
    assert len(results[0]["content"]) == 11
    assert results[1]["content"]["name"] == "Ипотека"
    assert len(results[2]["content"]) == 3


def test_later_writes_are_skipped_after_a_failure(http, make):
    agent, session, _ = make(
        calls(("create_tag", {"name": "Вклад"}), ("create_tag", {"name": "Новый"})), "Ошибка",
    )
    agent.send(session, "x")
    agent.decide(session, True)
    first, second = last_results(session)
    assert first["content"]["errors"][0]["code"] == "VALIDATION_ERROR"
    assert second["is_error"]
    assert "Новый" not in [t["name"] for t in http.get("/tags").json()]


def test_invalid_generated_banner_is_rejected_before_anything_else(make):
    bad = {**BANNER, "content": {"actionType": "externalLink", "background": {"color": "#FFF"}}}
    agent, session, _ = make(calls(("draft_upsert_banner", bad)), "Исправлю")
    agent.send(session, "x")
    outcome = last_results(session)[0]
    assert outcome["is_error"]
    assert {e["code"] for e in outcome["content"]["errors"]} == {"VALIDATION_ERROR"}
    assert session.draft.banners == {}


def test_title_over_limit_is_explained_with_numbers(make):
    bad = {**BANNER, "content": {"actionType": "default", "title": "я" * 132}}
    agent, session, _ = make(calls(("draft_upsert_banner", bad)), "Сократить?")
    agent.send(session, "x")
    error = last_results(session)[0]["content"]["errors"][0]
    assert error["code"] == "VALIDATION_ERROR"
    assert "132" in error["message"]


def test_precheck_skips_confirmation_for_invalid_write(make):
    agent, session, _ = make(
        calls(("create_banner", {"campaignId": 101, **{k: v for k, v in BANNER.items() if k != "key"},
                                 "content": {"actionType": "doneCampaign", "link": {"web": "https://x"}}})),
        "Исправлю",
    )
    turn = agent.send(session, "x")
    assert turn.confirmation is None
    assert "запрещён" in last_results(session)[0]["content"]["errors"][0]["message"]


def test_apply_is_refused_for_invalid_draft(make):
    agent, session, _ = make(calls(("apply_draft", {})), "Не хватает данных")
    assert agent.send(session, "x").confirmation is None
    codes = {e["field"] for e in last_results(session)[0]["content"]["errors"]}
    assert codes >= {"name", "places"}


def test_apply_is_refused_without_creatives(make):
    agent, session, _ = make(calls(
        ("draft_update_campaign", {**CAMPAIGN, "audienceType": "ALL_USERS"}), ("apply_draft", {}),
    ), "Соберу креативы")
    assert agent.send(session, "x").confirmation is None
    assert last_results(session)[1]["content"]["errors"][0]["field"] == "creatives"


def test_review_reports_real_problems(make):
    agent, session, _ = make(calls(
        ("draft_update_campaign", {**CAMPAIGN, "name": "Сомелье: подбор вина", "places": [4], "tags": []}),
        ("draft_set_segments", {"included": ["SEG_DRAFT_WINTER", "AGE_18_25", "AGE_60_PLUS"]}),
        ("draft_upsert_banner", BANNER),
        ("draft_set_creatives", {"creatives": [{"name": "w", "bannerKey": "story", "channelCode": "WEB"}]}),
        ("draft_review", {}),
    ), "Вот проблемы")
    agent.send(session, "x")
    review = last_results(session)[-1]["content"]
    assert {e["field"] for e in review["errors"]} == {"name", "included", "channelCode"}
    assert {e["code"] for e in review["errors"]} == {"NAME_DUPLICATE", "VALIDATION_ERROR"}
    assert sorted(review["warnings"]) == ["Некоторые места показа деактивированы", "У кампании отсутствуют теги"]
    assert [a["code"] for a in review["advisories"]] == ["AGE_GROUPS_NOT_ADJACENT", "CREATIVE_WITHOUT_CONTENT"]


def test_draft_warnings_agree_with_backend(http, make):
    agent, session, _ = make(fill_draft(), calls(("apply_draft", {})), "ok")
    agent.send(session, "x")
    predicted = last_results(session)[-1]["content"]["warnings"]
    agent.decide(session, True)
    actual = http.get(f"/campaigns/{session.draft.campaign_id}/warnings").json()["warnings"]
    assert predicted == actual


def test_failed_apply_resumes_without_duplicates(http, make):
    agent, session, _ = make(fill_draft(), calls(("apply_draft", {})), "Сбой", calls(("apply_draft", {})), "Готово")
    agent.send(session, "x")

    real_request = agent.backend.http.request
    def failing(method, path, **kwargs):
        if path.endswith("/creatives") and method == "POST":
            return http.post("/campaigns/101/creatives", json={}, headers={"X-User": "a", "X-Role": "campaignManager"})
        return real_request(method, path, **kwargs)

    agent.backend.http = SimpleNamespace(request=failing)
    agent.decide(session, True)
    assert last_results(session)[0]["is_error"]
    assert session.draft.campaign_id is not None
    assert not session.draft.finished

    agent.backend.http = http
    agent.send(session, "Повтори")
    agent.decide(session, True)
    campaign = http.get(f"/campaigns/{session.draft.campaign_id}").json()
    assert [len(campaign[k]) for k in ("banners", "contents", "creatives")] == [1, 1, 2]
    assert session.draft.finished


def filled_with(campaign=CAMPAIGN, banner=BANNER, creatives=CREATIVES):
    return calls(
        ("draft_update_campaign", campaign),
        ("draft_set_segments", {"included": ["CITY_MSK"], "excluded": []}),
        ("draft_upsert_banner", banner),
        ("draft_upsert_content", CONTENT),
        ("draft_set_creatives", creatives),
    )


@pytest.mark.parametrize("draft, field", [
    (filled_with(campaign={k: v for k, v in CAMPAIGN.items() if k not in ("endDate", "endTime")}), "endDate"),
    (filled_with(banner={**BANNER, "content": {"actionType": "default"}}), "banners.story"),
    (filled_with(banner={**BANNER, "content": {"title": "Скидка 15% по коду MOSCOW15", "actionType": "default"}}), "MOSCOW15"),
])
def test_incomplete_draft_is_not_offered_for_confirmation(make, draft, field):
    agent, session, llm = make(draft, calls(("apply_draft", {})), "Уточняю")
    turn = agent.send(session, "x")
    assert turn.confirmation is None
    assert field in str(llm.seen[-1])


def test_condition_from_the_brief_is_allowed(make):
    banner = {**BANNER, "content": {"title": "Скидка 15%", "actionType": "default"}}
    agent, session, _ = make(filled_with(banner=banner), calls(("apply_draft", {})))
    assert agent.send(session, "Сделай скидку 15% новым клиентам").confirmation


def test_single_promo_binds_to_creatives(make):
    agent, session, _ = make(
        filled_with(creatives={"creatives": [{"name": "iOS", "bannerKey": "story", "channelCode": "iOS"}]}), "Готово",
    )
    agent.send(session, "x")
    assert session.draft.creatives[0]["contentKey"] == "promo"


def test_open_end_needs_an_explicit_flag(make):
    campaign = {**{k: v for k, v in CAMPAIGN.items() if k not in ("endDate", "endTime")}, "noEndDate": True}
    agent, session, _ = make(filled_with(campaign=campaign), calls(("apply_draft", {})))
    assert agent.send(session, "x").confirmation
    assert "noEndDate" not in session.draft.campaign


def test_draft_edits_after_a_failure_reach_the_backend(http, make):
    agent, session, _ = make(
        fill_draft(), calls(("apply_draft", {})), "Сбой",
        calls(("draft_update_campaign", {"name": "Вклад 17%"})), calls(("apply_draft", {})), "Готово",
    )
    agent.send(session, "x")
    real_request = agent.backend.http.request

    def failing(method, path, **kwargs):
        if path.endswith("/creatives"):
            return http.post("/campaigns/101/creatives", json={}, headers={"X-User": "a", "X-Role": "campaignManager"})
        return real_request(method, path, **kwargs)

    agent.backend.http = SimpleNamespace(request=failing)
    agent.decide(session, True)
    agent.backend.http = http
    agent.send(session, "Поменяй название")
    agent.decide(session, True)
    assert http.get(f"/campaigns/{session.draft.campaign_id}").json()["name"] == "Вклад 17%"


def test_applied_draft_cannot_be_applied_twice(http, make):
    agent, session, _ = make(fill_draft(), calls(("apply_draft", {})), "ok", calls(("apply_draft", {})), "Уже")
    agent.send(session, "x")
    agent.decide(session, True)
    assert agent.send(session, "Ещё раз").confirmation is None
    assert "уже применён" in last_results(session)[0]["content"]["errors"][0]["message"]


def test_partial_update_keeps_other_fields(http, make):
    agent, session, _ = make(calls(("update_campaign", {"campaignId": 101, "weight": 20.0})), "Готово")
    agent.send(session, "x")
    agent.decide(session, True)
    campaign = http.get("/campaigns/101").json()
    assert campaign["weight"] == 20.0
    assert (campaign["tags"], campaign["places"], campaign["topic"]) == ([4, 3], [2], "SALES")


def test_role_comes_from_session_not_from_the_model(http, make):
    agent, session, _ = make(calls(("approve_campaign", {"campaignId": 103})), "Нельзя")
    agent.send(session, "Одобри")
    agent.decide(session, True)
    assert last_results(session)[0]["content"]["errors"][0]["code"] == "ROLE_FORBIDDEN"
    assert http.get("/campaigns/103").json()["state"] == "ON_MODERATION"


def test_moderator_can_decline_with_confirmation(http, make):
    agent, session, _ = make(
        calls(("decline_campaign", {"campaignId": 103, "comment": "Нет условий"})), "Отклонено", who=MODERATOR,
    )
    agent.send(session, "Отклони")
    assert http.get("/campaigns/103").json()["state"] == "ON_MODERATION"
    agent.decide(session, True)
    assert http.get("/campaigns/103").json()["state"] == "NEEDS_WORK"
    assert http.get("/campaigns/103/audit").json()[-1]["comment"] == "Нет условий"


def test_journal_records_actions_and_decisions(make, tmp_path):
    agent, session, _ = make(calls(("create_tag", {"name": "Новый"})), "ok")
    agent.send(session, "x")
    agent.decide(session, True)
    entries = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    entries = [e for e in entries if e["event"] != "llm_call"]
    assert [e["event"] for e in entries] == ["approved", "tool_call"]
    assert entries[1]["user"] == "ivanov.p"
    assert entries[1]["tool"] == "create_tag"


def test_llm_failure_keeps_session_usable(make):
    agent, session, _ = make(LLMError("Нет доступа"), "Привет")
    assert agent.send(session, "x").error == "Нет доступа"
    assert agent.send(session, "ещё раз").text == "Привет"


def test_refusal_is_reported(make):
    agent, session, _ = make(LLMResponse("", stop_reason="refusal", raw=[]))
    assert agent.send(session, "x").error


def test_unknown_tool_is_reported_to_the_model(make):
    agent, session, _ = make(calls(("hack", {})), "Ок")
    agent.send(session, "x")
    assert last_results(session)[0]["is_error"]


def test_step_limit_stops_the_loop(make):
    agent, session, _ = make(*[calls(("get_topics", {}))] * 30)
    assert "шагов" in agent.send(session, "x").error


def test_decide_without_pending(make):
    agent, session, _ = make()
    assert agent.decide(session, True).error


def test_wrap_refs_uses_dictionary_labels():
    d = Dictionaries(
        topics=[{"value": "SALES", "label": "Продажи"}], tags=[{"id": 5, "name": "Вклад"}],
        places=[{"id": 1, "code": "mainScreenStories"}], segments=[], banner_types=[], channels=[], campaign_names={},
    )
    payload = wrap_refs({"topic": "SALES", "tags": [5], "places": [1], "keywords": None}, d)
    assert payload["topic"] == {"value": "SALES", "label": "Продажи"}
    assert payload["tags"] == [{"value": 5, "label": "Вклад"}]
    assert payload["places"] == [{"value": 1, "label": "mainScreenStories"}]
    assert "keywords" not in payload


def test_dictionaries_are_in_every_context(make):
    seen = []

    class Recording(ScriptedLLM):
        def complete(self, system, context, messages, tools):
            seen.append(context)
            return super().complete(system, context, messages, tools)

    agent, session, _ = make("ok")
    agent.llm = Recording("ok")
    agent.send(session, "x")
    assert "CITY_MSK" in seen[0]
    assert "mainScreenStories" in seen[0]
    assert "Продажи" in seen[0]
    assert len(seen[0]) < 12000


def test_new_tag_reaches_the_next_context(http, make):
    seen = []

    class Recording(ScriptedLLM):
        def complete(self, system, context, messages, tools):
            seen.append(context)
            return super().complete(system, context, messages, tools)

    agent, session, _ = make()
    agent.llm = Recording("ok")
    http.post("/tags", json={"name": "Ипотека"}, headers={"X-User": "a", "X-Role": "campaignManager"})
    agent.send(session, "x")
    assert "Ипотека" in seen[0]


def test_backend_outage_is_reported_without_calling_the_model(make):
    agent, session, llm = make("ok")

    def down(*args, **kwargs):
        raise BackendError(503, [])

    agent.backend = SimpleNamespace(request=down)
    assert agent.send(session, "x").error == "Сервис кампаний недоступен"
    assert llm.seen == []


def test_creative_without_promo_gets_advice(make):
    creatives = {"creatives": [{"name": "c", "bannerKey": "story", "channelCode": "iOS"}]}
    agent, session, _ = make(calls(
        ("draft_upsert_banner", BANNER), ("draft_set_creatives", creatives), ("draft_review", {}),
    ), "ok")
    agent.send(session, "x")
    advisories = last_results(session)[-1]["content"]["advisories"]
    assert [a["code"] for a in advisories] == ["CREATIVE_WITHOUT_CONTENT"]


def test_journal_names_the_model(make, tmp_path):
    agent, session, _ = make(LLMResponse("ok", raw=[], model="m1"))
    agent.send(session, "x")
    entries = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert entries[0]["event"] == "llm_call"
    assert entries[0]["model"] == "m1"


def test_repeated_failures_stop_the_loop(make):
    bad = {**BANNER, "content": {"background": "x"}}
    agent, session, llm = make(*[calls(("draft_upsert_banner", bad))] * 10)
    turn = agent.send(session, "x")
    assert "Не получилось" in turn.error
    assert len(llm.seen) == 3


def test_failure_counter_resets_after_success(make):
    bad = {**BANNER, "content": {"background": "x"}}
    agent, session, _ = make(
        calls(("draft_upsert_banner", bad)), calls(("draft_upsert_banner", bad)), calls(("get_topics", {})),
        calls(("draft_upsert_banner", bad)), calls(("draft_upsert_banner", bad)), "Готово",
    )
    assert agent.send(session, "x").text == "Готово"


def test_missing_required_field_goes_back_to_the_model(make):
    agent, session, _ = make(calls(("get_campaign", {})), "Какую кампанию?")
    assert agent.send(session, "x").text == "Какую кампанию?"
    outcome = last_results(session)[0]
    assert outcome["is_error"] and "campaignId" in outcome["content"]["reason"]


def test_draft_reset(make):
    agent, session, _ = make(fill_draft(), calls(("draft_reset", {})), "ok")
    agent.send(session, "x")
    assert session.draft == Draft()


@pytest.fixture
def client(tmp_path):
    def factory(*turns):
        backend = Backend(TestClient(create_backend(tmp_path / "test.db")))
        return TestClient(create_app(Agent(ScriptedLLM(*turns), backend, Journal(tmp_path / "j.jsonl"))))
    return factory


def events(response):
    return [json.loads(line) for line in response.text.splitlines()]


def new_session(api):
    return api.post("/sessions", json={}).json()["id"]


def test_empty_session_state(client):
    state = client().post("/sessions", json={"user": "petrova.m", "role": "campaignModerator"}).json()
    assert state["role"] == "campaignModerator"
    assert state["progress"]["percent"] == 0
    assert "Название" in state["progress"]["missing"]
    assert state["awaitingConfirmation"] is False


def test_message_streams_statuses_then_state(client):
    api = client(fill_draft(), "Вот сводка")
    sid = new_session(api)
    result = events(api.post(f"/sessions/{sid}/messages", json={"text": "Бриф"}))

    labels = [e["label"] for e in result if e["type"] == "status"]
    assert "Подбираю аудиторию" in labels
    assert "Проверяю ограничения" in labels

    final = result[-1]
    assert final["turn"]["text"] == "Вот сводка"
    assert final["session"]["progress"]["percent"] == 100
    assert final["session"]["review"]["ready"] is True


def test_confirmation_flow(client):
    api = client(fill_draft(), calls(("apply_draft", {})), "Создано")
    sid = new_session(api)
    final = events(api.post(f"/sessions/{sid}/messages", json={"text": "Бриф"}))[-1]
    assert final["turn"]["confirmation"][0]["tool"] == "apply_draft"
    assert final["session"]["awaitingConfirmation"] is True

    final = events(api.post(f"/sessions/{sid}/decision", json={"approved": True}))[-1]
    assert final["turn"]["text"] == "Создано"
    assert final["session"]["draft"]["campaignId"] is not None


def test_end_date_counts_as_answered_only_when_discussed(client):
    start_only = {k: v for k, v in CAMPAIGN.items() if k not in ("endDate", "endTime")}
    api = client(calls(("draft_update_campaign", start_only)), "Когда заканчиваем?")
    sid = new_session(api)
    final = events(api.post(f"/sessions/{sid}/messages", json={"text": "Бриф"}))[-1]
    assert "Окончание показа" in final["session"]["progress"]["missing"]


def test_unknown_session(client):
    assert client().get("/sessions/none").status_code == 404


def completion(message, finish="stop"):
    return ChatCompletion.model_validate({
        "choices": [{"message": {"role": "assistant", **message}, "index": 0, "finish_reason": finish}],
        "created": 1, "model": "m", "object": "chat.completion",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


def fake_client(result):
    seen = {}

    def chat(payload):
        seen["chat"] = payload
        if isinstance(result, Exception):
            raise result
        return result

    return SimpleNamespace(chat=chat), seen


def has_key(value, key):
    if isinstance(value, dict):
        return key in value or any(has_key(v, key) for v in value.values())
    if isinstance(value, list):
        return any(has_key(v, key) for v in value)
    return False


def test_all_tools_become_plain_functions():
    for definition in TOOL_DEFINITIONS:
        schema = plain_schema(definition["input_schema"])
        for key in ("$ref", "$defs", "anyOf", "oneOf"):
            assert not has_key(schema, key), definition["name"]
        assert to_function(definition).name == definition["name"]


def test_nullable_field_keeps_its_type_and_description():
    schema = plain_schema(TOOLS["draft_update_campaign"].definition()["input_schema"])
    assert schema["properties"]["startDate"] == {"type": "string", "description": "YYYY-MM-DD"}
    assert schema["properties"]["tags"]["items"] == {"type": "integer"}


def test_union_of_objects_keeps_all_fields():
    schema = plain_schema(TOOLS["draft_upsert_content"].definition()["input_schema"])
    component = schema["properties"]["content"]["properties"]["component"]
    fields = component["properties"]["components"]["items"]["properties"]
    assert fields["role"]["enum"] == ["button", "image", "text"]
    assert {"format", "text", "url", "actionType"} <= fields.keys()


def test_limits_reach_the_model_through_description():
    schema = plain_schema(TOOLS["create_banner"].definition()["input_schema"])
    content = schema["properties"]["content"]["properties"]
    assert "200" in content["voiceOver"]["description"]
    assert "maxLength" not in content["voiceOver"]
    assert "#" in content["background"]["properties"]["color"]["description"]


def test_every_object_has_properties():
    def check(schema):
        if schema.get("type") == "object":
            assert "properties" in schema
        for value in schema.get("properties", {}).values():
            check(value)
        if "items" in schema:
            check(schema["items"])

    for definition in TOOL_DEFINITIONS:
        check(plain_schema(definition["input_schema"]))


def test_referenced_object_is_inlined():
    schema = plain_schema(TOOLS["draft_upsert_banner"].definition()["input_schema"])
    assert "actionType" in schema["properties"]["content"]["properties"]


def test_request_shape():
    client, seen = fake_client(completion({"content": "Привет"}))
    tools = [TOOLS["get_topics"].definition()]
    result = GigaChatLLM(client, "m").complete("system", "контекст", [{"role": "user", "text": "x"}], tools)
    assert (result.text, result.stop_reason) == ("Привет", "end_turn")
    chat = seen["chat"]
    assert chat.messages[0].role == MessagesRole.SYSTEM
    assert chat.messages[0].content == "system\n\nконтекст"
    assert chat.function_call == "auto"
    assert chat.functions[0].name == "get_topics"


def test_function_call_round_trip():
    parsed = parse_response(completion(
        {"content": "", "function_call": {"id": "call-1", "name": "get_tags", "arguments": {"a": 1}}, "functions_state_id": "state-1"},
        "function_call",
    ), "m")
    call = parsed.tool_calls[0]
    assert (parsed.stop_reason, call.id, call.input) == ("tool_use", "call-1", {"a": 1})
    assert to_gigachat({"role": "assistant", "raw": parsed.raw}) == [parsed.raw]

    messages = to_gigachat({
        "role": "tool",
        "results": [{"id": call.id, "name": call.name, "content": [{"id": 1}], "is_error": False}],
        "text": "ещё",
    })
    assert messages[0].role == MessagesRole.FUNCTION
    assert messages[0].name == "get_tags"
    assert messages[0].id_ == "call-1"
    assert messages[0].functions_state_id is None
    assert json.loads(messages[0].content) == {"result": [{"id": 1}]}
    assert messages[1].content == "ещё"


def test_call_without_state_id_gets_local_id():
    parsed = parse_response(completion({"content": "", "function_call": {"name": "x", "arguments": {}}}, "function_call"), "m")
    assert parsed.tool_calls[0].id.startswith("local-")
    message = to_gigachat({"role": "tool", "results": [
        {"id": parsed.tool_calls[0].id, "name": "x", "content": {"ok": True}, "is_error": False},
    ]})[0]
    assert message.id_ is None


@pytest.mark.parametrize("finish, stop_reason", [("blacklist", "refusal"), ("length", "max_tokens")])
def test_finish_reasons(finish, stop_reason):
    assert parse_response(completion({"content": "x"}, finish), "m").stop_reason == stop_reason


def test_rate_limit_becomes_llm_error(monkeypatch):
    monkeypatch.setattr("backend.llm.RETRY_DELAYS", (0,))
    client, _ = fake_client(RateLimitError("http://x", 429, b"limit", None))
    with pytest.raises(LLMError, match="Лимит"):
        GigaChatLLM(client).complete("s", "c", [{"role": "user", "text": "x"}], [])


def test_dropped_connection_is_retried_once(monkeypatch):
    monkeypatch.setattr("backend.llm.RETRY_DELAYS", (0,))
    answers = [httpx.RemoteProtocolError("разрыв"), completion({"content": "Привет"})]

    def chat(_):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    result = GigaChatLLM(SimpleNamespace(chat=chat)).complete("s", "c", [{"role": "user", "text": "x"}], [])
    assert result.text == "Привет"


def test_repeated_disconnect_becomes_llm_error(monkeypatch):
    monkeypatch.setattr("backend.llm.RETRY_DELAYS", (0,))
    client, _ = fake_client(httpx.RemoteProtocolError("разрыв"))
    with pytest.raises(LLMError, match="соединиться"):
        GigaChatLLM(client).complete("s", "c", [{"role": "user", "text": "x"}], [])


def test_system_role_is_not_lost_between_messages():
    assert isinstance(to_gigachat({"role": "user", "text": "x"})[0], Messages)


def test_draw_returns_generated_file():
    answers = [completion({"content": "автомобиль."}), completion({"content": '<img src="file-1" fuse="true"/>'})]
    prompts = []

    def chat(payload):
        prompts.append(payload.messages[0].content)
        return answers.pop(0)

    client = SimpleNamespace(chat=chat, get_image=lambda file_id: SimpleNamespace(content=base64.b64encode(file_id.encode()).decode()))
    assert GigaChatLLM(client).draw("Автокредит от 7,9%") == b"file-1"
    assert "Автокредит" in prompts[0]
    assert "автомобиль" in prompts[1] and "Автокредит" not in prompts[1]


def test_draw_without_picture_is_an_error():
    client, _ = fake_client(completion({"content": "Не могу нарисовать"}))
    with pytest.raises(LLMError, match="изображение"):
        GigaChatLLM(client).draw("x")


def test_image_is_drawn_once_and_failure_pauses_generation(tmp_path):
    drawn = []

    def draw(brief):
        drawn.append(brief)
        if brief == "сбой":
            raise LLMError("нет")
        return b"jpeg"

    agent = SimpleNamespace(llm=SimpleNamespace(draw=draw))
    api = TestClient(create_app(agent, tmp_path / "images"))
    assert api.get("/image", params={"brief": "кофе"}).content == b"jpeg"
    assert api.get("/image", params={"brief": "кофе"}).headers["content-type"] == "image/jpeg"
    assert drawn == ["кофе"]
    assert api.get("/image", params={"brief": "сбой"}).status_code == 502
    assert api.get("/image", params={"brief": "сбой"}).status_code == 503
    assert drawn.count("сбой") == 1


@pytest.mark.parametrize("campaign, brief, weight", [
    ({"topic": "COURSES", "audienceType": "SEGMENTED"}, "курс", 2),
    ({"topic": "EVENT", "startDate": "2026-11-01", "endDate": "2026-11-10", "audienceType": "ALL_USERS"}, "важно", 12),
    ({"topic": "SALES", "startDate": "2026-11-01", "endDate": "2026-12-20"}, "максимально широкий охват", 8),
    ({"startDate": "2026-11-01", "endDate": "2027-11-01"}, "", 1),
])
def test_suggested_weight(campaign, brief, weight):
    assert suggest_weight(campaign, brief)["weight"] == weight


def test_weight_is_set_by_criteria_and_model_cannot_override_it(make):
    agent, session, _ = make(filled_with(campaign={**CAMPAIGN, "weight": 50}), "Готово")
    agent.send(session, "x")
    assert session.draft.campaign["weight"] == 6  # SALES +5, срок почти два месяца +1
    assert session.draft.weight_reasons == ["тема +5", "короткий срок +1"]


def test_manager_can_set_own_weight(make):
    agent, session, _ = make(filled_with(campaign={**CAMPAIGN, "weight": 9}), "Готово")
    agent.send(session, "Поставь вес 9")
    assert session.draft.campaign["weight"] == 9
    assert session.draft.weight_reasons == []


def test_new_tag_uses_edited_form_and_binds_to_draft(make, http):
    agent, session, _ = make(
        calls(("draft_update_campaign", CAMPAIGN)), calls(("create_tag", {"name": "Новый тэг"})), "Готово",
    )
    turn = agent.send(session, "x")
    assert turn.confirmation[0]["tool"] == "create_tag"
    agent.decide(session, True, edits={"name": "Новый тег", "id": 1})
    created = next(tag for tag in http.get("/tags").json() if tag["name"] == "Новый тег")
    assert created["id"] in session.draft.campaign["tags"]


def test_image_prompt_forbids_people():
    assert "Без людей" in IMAGE_PROMPT


def test_opened_campaign_is_updated_not_copied(make, http):
    before = len(http.get("/campaigns").json())
    agent, session, _ = make(
        calls(("draft_open_campaign", {"campaignId": 101})),
        calls(("draft_update_campaign", {"marketingName": "Новое"})),
        calls(("apply_draft", {})), "Готово",
    )
    assert agent.send(session, "Исправь кампанию 101").confirmation
    agent.decide(session, True)
    assert len(http.get("/campaigns").json()) == before
    assert http.get("/campaigns/101").json()["marketingName"] == "Новое"


def test_mentioned_campaign_cannot_be_replaced_by_a_new_one(make):
    agent, session, llm = make(filled_with(), calls(("apply_draft", {})), "Открою кампанию")
    assert agent.send(session, "Исправь кампанию 104").confirmation is None
    assert "draft_open_campaign" in str(llm.seen[-1])


def test_moderation_needs_a_direct_request(make):
    agent, session, llm = make(calls(("to_moderation", {"campaignId": 101})), "Отправить?")
    assert agent.send(session, "Покажи кампанию 101").confirmation is None
    assert "не просил" in str(llm.seen[-1])

    agent, session, _ = make(calls(("to_moderation", {"campaignId": 101})), "Готово")
    assert agent.send(session, "Отправляй на модерацию").confirmation


@pytest.mark.parametrize("content, word", [
    ({"title": "Выучите за 2 недели", "actionType": "default"}, "2"),
])
def test_invented_facts_do_not_pass(make, content, word):
    agent, session, llm = make(filled_with(banner={**BANNER, "content": content}), calls(("apply_draft", {})), "Убираю")
    assert agent.send(session, "x").confirmation is None
    assert word in str(llm.seen[-1])


def test_known_link_is_allowed(make):
    content = {"title": "Карта", "actionType": "externalLink", "link": {"iOS": "mobilebank://products/card/premium"}}
    agent, session, llm = make(filled_with(banner={**BANNER, "content": content}), calls(("apply_draft", {})), "стоп")
    assert agent.send(session, "x").confirmation, llm.seen[-1][-1]


def test_question_gets_only_reading_tools(make):
    agent, session, llm = make("Отвечаю", "Отвечаю")
    agent.send(session, "Почему отклонили кампанию 104?")
    assert {tool["name"] for tool in llm.tools} >= {"get_campaign", "get_campaign_audit"}
    assert not any(tool["name"].startswith(("draft_", "apply", "to_")) for tool in llm.tools)
    agent.send(session, "Исправь её")
    assert any(tool["name"] == "draft_open_campaign" for tool in llm.tools)


def test_number_inside_another_is_not_a_source(make):
    banner = {**BANNER, "content": {"title": "Курс за 2 недели", "actionType": "default"}}
    agent, session, _ = make(filled_with(banner=banner), calls(("apply_draft", {})), "Убираю")
    assert agent.send(session, "С 5 по 20 ноября").confirmation is None


def test_invented_link_is_removed_from_draft(make):
    content = {"title": "Карта", "actionType": "externalLink", "link": {"iOS": "mobilebank://products/deposit"}}
    agent, session, _ = make(filled_with(banner={**BANNER, "content": content}), "Готово")
    agent.send(session, "x")
    assert session.draft.banners["story"]["content"]["actionType"] == "default"
    assert "link" not in session.draft.banners["story"]["content"]


@pytest.mark.parametrize("state, published, allowed, forbidden", [
    ("ACTIVE", True, "можно_остановить", "можно_удалить"),
    ("STOPPED", False, None, "можно_активировать"),
    ("ON_MODERATION", False, None, "можно_править"),
    ("NEEDS_WORK", False, "можно_удалить", "можно_активировать"),
])
def test_lifecycle_facts(state, published, allowed, forbidden):
    facts = lifecycle_facts(state, published)
    assert not facts[forbidden]
    assert allowed is None or facts[allowed]


def test_campaign_tool_returns_lifecycle(make):
    agent, session, llm = make(calls(("get_campaign", {"campaignId": 102})), "Ответ")
    agent.send(session, "Что с кампанией 102?")
    assert "можно_остановить" in str(llm.seen[-1])
