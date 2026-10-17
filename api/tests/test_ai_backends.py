import json

import pytest
from fastapi.testclient import TestClient

from app.ai import AIError, _PostDraft
from app.ai_backends import GeminiBackend, JsonLLMProvider, OpenAIBackend, parse_json_reply
from app.brief_schemas import SuggestRequest
from app.config import Settings
from app.http import HttpResponse
from app.main import build_ai, create_app
from tests.conftest import ADMIN, login, make_settings, register


class Http:
    """Fake `http` callable: queued HttpResponses (or exceptions), remembers each request."""

    def __init__(self, *queue):
        self.queue, self.calls = list(queue), []

    def __call__(self, method, url, *, headers=None, form=None, json_body=None, timeout=20.0):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json_body})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(status=200, body=None):
    return HttpResponse(status, json.dumps(body).encode() if body is not None else b"", {})


DRAFT = {"post": "Hello world", "alternative_hooks": ["a", "b"], "notes": "n"}


def openai_ok(content, finish="stop", usage=(11, 7), **message):
    return resp(200, {"choices": [{"message": {"content": content, **message}, "finish_reason": finish}], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}})


def gemini_ok(text, finish="STOP", usage=(11, 7), extra=None):
    return resp(200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}], "usageMetadata": {"promptTokenCount": usage[0], "candidatesTokenCount": usage[1]}, **(extra or {})})


def openai_provider(http, base="https://api.openai.com/v1", key="sk-test", **kw):
    return JsonLLMProvider("openai", OpenAIBackend(key, base, "some-model", http=http, **kw), "some-model")


def gemini_provider(http):
    return JsonLLMProvider("gemini", GeminiBackend("g-key", "https://generativelanguage.googleapis.com/v1beta", "models/some-gemini", http=http), "some-gemini")


# --- reply parsing ---------------------------------------------------------------

@pytest.mark.parametrize("text", [json.dumps(DRAFT), "```json\n" + json.dumps(DRAFT) + "\n```", "Sure! Here you go:\n" + json.dumps(DRAFT) + "\nHope it helps.", "  " + json.dumps(DRAFT) + "  "])
def test_json_replies_survive_fences_and_chatter(text):
    assert parse_json_reply(text, _PostDraft).post == "Hello world"


def test_invalid_replies_raise():
    for bad in ("", "not json", '{"post": 5}', '{"alternative_hooks": []}'):
        with pytest.raises(ValueError):
            parse_json_reply(bad, _PostDraft)


# --- OpenAI protocol ---------------------------------------------------------------

def test_openai_request_shape_and_result():
    http = Http(openai_ok(json.dumps(DRAFT)))
    out = openai_provider(http).draft_post({"post": {"topic": "t"}})
    assert out.post == "Hello world" and out.input_tokens == 11 and out.output_tokens == 7 and out.model == "some-model"
    call = http.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions" and call["headers"]["Authorization"] == "Bearer sk-test"
    body = call["json"]
    assert body["model"] == "some-model" and body["response_format"] == {"type": "json_object"} and body["max_completion_tokens"] == 6000 and "max_tokens" not in body
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    assert "JSON Schema" in system and '"post"' in system and "<data>" in user  # the schema is in the prompt, the data is fenced


def test_compatible_servers_get_max_tokens_and_optional_auth():
    http = Http(openai_ok(json.dumps(DRAFT)))
    openai_provider(http, base="http://localhost:11434/v1/", key=None).draft_post({})
    call = http.calls[0]
    assert call["url"] == "http://localhost:11434/v1/chat/completions" and "Authorization" not in call["headers"]
    assert call["json"]["max_tokens"] == 6000 and "max_completion_tokens" not in call["json"]
    http = Http(openai_ok(json.dumps(DRAFT)))
    openai_provider(http, token_param="max_tokens").draft_post({})
    assert http.calls[0]["json"]["max_tokens"] == 6000


def test_unusable_reply_is_retried_once_with_the_error_and_tokens_add_up():
    http = Http(openai_ok("sorry, no JSON", usage=(10, 5)), openai_ok(json.dumps(DRAFT), usage=(12, 6)))
    out = openai_provider(http).draft_post({})
    assert out.post == "Hello world" and (out.input_tokens, out.output_tokens) == (22, 11)
    assert "could not be used" in http.calls[1]["json"]["messages"][1]["content"]
    with pytest.raises(AIError, match="could not be read"):
        openai_provider(Http(openai_ok("nope"), openai_ok("still nope"))).draft_post({})


def test_truncated_and_refused_replies():
    with pytest.raises(AIError, match="cut off"):
        openai_provider(Http(openai_ok('{"post": "abc', finish="length"), openai_ok('{"post": "abc', finish="length"))).draft_post({})
    http = Http(openai_ok('{"post": "abc', finish="length"), openai_ok(json.dumps(DRAFT)))
    assert openai_provider(http).draft_post({}).post == "Hello world"  # a second try can succeed
    for refused in (openai_ok(None, refusal="I can't help with that"), openai_ok("", finish="content_filter")):
        with pytest.raises(AIError, match="declined"):
            openai_provider(Http(refused)).draft_post({})


@pytest.mark.parametrize("status,expected_code,expected_text", [(401, 503, "misconfigured"), (403, 503, "misconfigured"), (429, 503, "busy"), (500, 502, "error (500)"), (400, 502, "does not exist"), (404, 502, "does not exist")])
def test_http_errors_map_to_clear_messages(status, expected_code, expected_text):
    http = Http(resp(status, {"error": {"message": "The model `x` does not exist"}}))
    with pytest.raises(AIError) as e:
        openai_provider(http).draft_post({})
    assert e.value.status_code == expected_code and expected_text in e.value.message
    assert "sk-test" not in e.value.message


def test_network_failure_and_garbage_shapes():
    with pytest.raises(AIError, match="Could not reach"):
        openai_provider(Http(OSError("boom"))).draft_post({})
    for odd in (resp(200, {"choices": []}), resp(200, ["x"]), resp(200, {"choices": [{"message": "str"}]})):
        with pytest.raises(AIError, match="could not be read"):
            openai_provider(Http(odd)).draft_post({})
    assert openai_provider(Http(openai_ok(json.dumps(DRAFT), usage=("x", None)))).draft_post({}).input_tokens == 0  # junk usage never crashes


# --- Gemini protocol ---------------------------------------------------------------

def test_gemini_request_shape_and_result():
    http = Http(gemini_ok(json.dumps(DRAFT)))
    out = gemini_provider(http).draft_post({"post": {"topic": "t"}})
    assert out.post == "Hello world" and (out.input_tokens, out.output_tokens) == (11, 7)
    call = http.calls[0]
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/models/some-gemini:generateContent"  # "models/" prefix not doubled
    assert call["headers"] == {"x-goog-api-key": "g-key"} and "key=" not in call["url"]  # key in a header, never in a URL that could be logged
    body = call["json"]
    assert body["generationConfig"] == {"responseMimeType": "application/json", "maxOutputTokens": 6000}
    assert "JSON Schema" in body["systemInstruction"]["parts"][0]["text"] and "<data>" in body["contents"][0]["parts"][0]["text"]


def test_gemini_multi_part_thoughts_blocks_and_errors():
    parts = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": json.dumps(DRAFT)[:10]}, {"text": json.dumps(DRAFT)[10:]}]}, "finishReason": "STOP"}]}
    assert gemini_provider(Http(resp(200, parts))).draft_post({}).post == "Hello world"
    with pytest.raises(AIError, match="declined"):
        gemini_provider(Http(resp(200, {"promptFeedback": {"blockReason": "SAFETY"}}))).draft_post({})
    with pytest.raises(AIError, match="declined"):
        gemini_provider(Http(gemini_ok("", finish="SAFETY"))).draft_post({})
    with pytest.raises(AIError, match="cut off"):
        gemini_provider(Http(gemini_ok("{", finish="MAX_TOKENS"), gemini_ok("{", finish="MAX_TOKENS"))).draft_post({})
    with pytest.raises(AIError, match="misconfigured"):
        gemini_provider(Http(resp(403, {"error": {"message": "API key not valid"}}))).draft_post({})
    with pytest.raises(AIError, match="could not be read"):
        gemini_provider(Http(resp(200, {"candidates": []}))).draft_post({})


# --- the other tasks work through the same path ------------------------------------

def test_all_four_tasks_run_on_a_json_vendor():
    suggestion = {"niche_statement": "Help X do Y", "unique_angle": "Z", "pillars": ["a", "b", "c"], "proof_assets_to_collect": [], "opinions_to_consider": [],
                  "platforms": [{"platform": "linkedin", "is_primary": True, "cadence_per_week": 4, "reason": "fit"}], "rationale": "because"}
    out = openai_provider(Http(openai_ok(json.dumps(suggestion)))).suggest_brief({"name": "Acme"}, SuggestRequest())
    assert out.ideation.niche_statement == "Help X do Y" and out.platforms[0].is_primary
    scores = openai_provider(Http(openai_ok(json.dumps({"items": [{"id": 1, "relevance": 150, "why": "fits"}, {"id": 99, "relevance": 5, "why": "stranger"}]})))).score_feed({}, None, [{"id": 1}])
    assert scores.scores == {1: (100, "fits")}  # clamped, and ids the app never sent are dropped
    reply = gemini_provider(Http(gemini_ok(json.dumps({"reply": "Try X.", "post_idea_title": "", "post_idea": "", "notes": ""})))).draft_reply({})
    assert reply.reply == "Try X." and reply.post_idea is None
    with pytest.raises(AIError, match="empty draft"):
        openai_provider(Http(openai_ok(json.dumps({**DRAFT, "post": "  "})))).draft_post({})


# --- choosing a vendor ---------------------------------------------------------------

def settings(**kw):
    return Settings(database_url="sqlite://", secret_key="x" * 40, **kw)


def test_auto_picks_the_first_vendor_with_credentials():
    assert settings().ai_vendor is None and build_ai(settings()) is None
    assert settings(anthropic_api_key="a", openai_api_key="o", gemini_api_key="g").ai_vendor == "anthropic"
    assert settings(openai_api_key="o", gemini_api_key="g", ai_model="m").ai_vendor == "openai"
    s = settings(gemini_api_key="g", ai_model="gem")
    assert s.ai_vendor == "gemini" and build_ai(s).name == "gemini" and build_ai(s).model == "gem"
    assert settings(anthropic_api_key="a").effective_ai_model == "claude-opus-5-5"
    assert settings(anthropic_api_key="a", ai_model="claude-x").effective_ai_model == "claude-x"


def test_explicit_provider_wins_and_a_custom_server_needs_no_key():
    s = settings(ai_provider="openai", openai_base_url="http://localhost:11434/v1", ai_model="llama", anthropic_api_key="a")
    s.assert_safe()
    p = build_ai(s)
    assert p.name == "openai" and p.model == "llama" and p.backend.api_key is None


@pytest.mark.parametrize("kw,message", [
    (dict(ai_provider="openai", ai_model="m"), "OPENAI_API_KEY"),
    (dict(ai_provider="gemini", ai_model="m"), "GEMINI_API_KEY"),
    (dict(ai_provider="anthropic"), "ANTHROPIC_API_KEY"),
    (dict(openai_api_key="o"), "SMM_AI_MODEL is required"),
    (dict(gemini_api_key="g"), "SMM_AI_MODEL is required"),
])
def test_misconfiguration_fails_at_startup_with_a_clear_message(kw, message):
    with pytest.raises(RuntimeError, match=message):
        settings(**kw).assert_safe()


def test_vendor_keys_are_read_from_their_usual_environment_variables(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-from-env")
    s = Settings(database_url="sqlite://", secret_key="x" * 40)
    assert s.openai_api_key == "sk-from-env" and s.gemini_api_key == "g-from-env"


# --- the app, end to end, and the admin endpoints ------------------------------------------

@pytest.fixture
def openai_app():
    http = Http(*[openai_ok(json.dumps({"ok": True}))] * 3)
    provider = JsonLLMProvider("openai", OpenAIBackend("sk-secret-key", "https://api.openai.com/v1", "m-1", http=http), "m-1")
    with TestClient(create_app(make_settings(), ai=provider)) as c:
        yield c, http


def test_admin_status_and_connection_test(openai_app):
    c, http = openai_app
    register(c, "alice@example.com")
    alice, admin = login(c, "alice@example.com"), login(c, ADMIN["email"], ADMIN["password"])
    assert c.get("/ai/status", headers=alice).status_code == 403 and c.post("/ai/test", headers=alice).status_code == 403
    status = c.get("/ai/status", headers=admin).json()
    assert status["configured"] and status["provider"] == "openai" and status["model"] == "m-1" and "sk-secret" not in json.dumps(status)
    r = c.post("/ai/test", headers=admin)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["model"] == "m-1" and len(http.calls) == 1


def test_connection_test_reports_failures_and_missing_config(fake_ai):
    http = Http(resp(401, {"error": {"message": "Incorrect API key provided: sk-secret-key"}}))
    provider = JsonLLMProvider("openai", OpenAIBackend("sk-secret-key", "https://api.openai.com/v1", "m", http=http), "m")
    with TestClient(create_app(make_settings(), ai=provider)) as c:
        r = c.post("/ai/test", headers=login(c, ADMIN["email"], ADMIN["password"]))
        assert r.status_code == 503 and "misconfigured" in r.json()["detail"] and "sk-secret-key" not in r.text
    with TestClient(create_app(make_settings())) as c:
        admin = login(c, ADMIN["email"], ADMIN["password"])
        assert c.get("/ai/status", headers=admin).json() == {"configured": False, "provider": None, "model": None, "base_url": None, "daily_limit_per_user": 20}
        assert c.post("/ai/test", headers=admin).status_code == 503


def test_a_real_endpoint_runs_on_an_openai_vendor():
    suggestion = {"niche_statement": "Help X do Y", "unique_angle": "Z", "pillars": ["a", "b", "c"], "proof_assets_to_collect": [], "opinions_to_consider": [],
                  "platforms": [{"platform": "linkedin", "is_primary": True, "cadence_per_week": 4, "reason": "fit"}], "rationale": "because"}
    provider = openai_provider(Http(openai_ok(json.dumps(suggestion))))
    with TestClient(create_app(make_settings(), ai=provider)) as c:
        register(c, "alice@example.com")
        h = login(c, "alice@example.com")
        vid = c.post("/ventures", json={"name": "Acme"}, headers=h).json()["id"]
        r = c.post(f"/ventures/{vid}/brief/suggest", json={}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ideation"]["niche_statement"] == "Help X do Y" and body["platforms"][0]["platform"] == "linkedin"
        assert c.get(f"/ventures/{vid}/brief", headers=h).status_code == 200
