import json
from datetime import datetime, timedelta, timezone
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from api import main
from core import llm
from core.scheduler import Scheduler, interval_seconds, parse_datetime
from database.models import Content, ScheduledJob
from database.publishing import beautify_content
from scraper import scraper
from scraper.utils import clean_html


@pytest.fixture
def client():
    with TestClient(main.app) as connection:
        yield connection


def test_topic_generation_is_saved_without_wordpress(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "generate_content",
        lambda topic, **kwargs: "# Test draft\n\nUseful original content.",
    )
    response = client.post("/generate_by_trend", json={"trend": "A useful topic"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] > 0 and data["trend"] is True
    assert data["wordpress_status"] == "local"
    assert client.get("/contents").json()[0]["body"] == data["body"]
    assert client.get(f"/contents/{data['id']}").status_code == 200
    assert client.delete(f"/contents/{data['id']}").status_code == 200
    assert client.get("/contents").json() == []


def test_url_generation_keeps_factual_source_context(client, monkeypatch):
    source = "The observatory opened in 1982. Its telescope has a 2 metre mirror."
    monkeypatch.setattr(main, "scrape_url", lambda url: source)
    monkeypatch.setattr(main, "analyze_topic", lambda excerpt: "Inside the observatory")

    def generate(topic, **kwargs):
        assert kwargs["source_text"] == source
        assert kwargs["source_url"] == "https://example.com/article"
        return "An article grounded in the source."

    monkeypatch.setattr(main, "generate_content", generate)
    response = client.post("/process", json={"url": "https://example.com/article"})
    assert response.status_code == 200, response.text
    assert response.json()["trend"] is False


def test_provider_failure_does_not_save_fake_content(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise llm.ModelUnavailable("Start the model server")

    monkeypatch.setattr(main, "generate_content", unavailable)
    response = client.post("/generate_by_trend", json={"trend": "A topic"})
    assert response.status_code == 503
    assert client.get("/contents").json() == []


def test_validation_and_protected_routes(client, monkeypatch):
    for path, payload in [
        ("/process", {}),
        ("/chat", {"message": "  "}),
        ("/schedule", {"job_name": "invalid"}),
        ("/generate_by_trend", {"source": "invalid"}),
    ]:
        assert client.post(path, json=payload).status_code == 422
    assert client.get("/contents/999").status_code == 404
    assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400
    assert (
        client.delete(
            "/flush_db", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    monkeypatch.setattr(main.config, "API_KEY", "test-key")
    assert client.get("/health").status_code == 200
    assert client.get("/contents").status_code == 401
    assert client.get("/contents", headers={"X-API-Key": "test-key"}).status_code == 200


def test_concurrent_generation_and_cancellation_preserve_database(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return "Generated result to discard"

    monkeypatch.setattr(main, "generate_content", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.post, "/generate_by_trend", json={"trend": "Slow topic"}
        )
        assert entered.wait(5)
        try:
            assert client.post("/chat", json={"message": "hello"}).status_code == 409
            assert client.delete("/flush_db").status_code == 409
            assert client.post("/cancel_all_jobs").status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 409
    assert client.get("/contents").json() == []


def test_explicit_wordpress_delivery_updates_existing_post(
    client, monkeypatch, isolated
):
    _, factory = isolated
    with factory() as db:
        row = Content(topic="A title", body="A draft", trend=True)
        db.add(row)
        db.commit()
        content_id = row.id
    seen = []

    def deliver(record, status):
        seen.append((record.wordpress_id, status))
        return {"id": 77, "url": "https://wordpress.test/article", "status": status}

    monkeypatch.setattr(main, "publish_content", deliver)
    assert (
        client.post(
            f"/contents/{content_id}/publish", json={"status": "draft"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/contents/{content_id}/publish", json={"status": "publish"}
        ).status_code
        == 200
    )
    assert seen == [(None, "draft"), (77, "publish")]
    assert client.get(f"/contents/{content_id}").json()["wordpress_status"] == "publish"


@pytest.mark.parametrize("value", ["-1:00:00", "00:60:00", "00:00:01", "bad"])
def test_invalid_intervals_rejected(value):
    with pytest.raises(ValueError):
        interval_seconds(value)


def test_scheduler_respects_interval_and_persists_state(isolated):
    _, factory = isolated
    calls = []
    scheduler = Scheduler(factory, lambda name, payload, abort: calls.append(name))
    scheduler.set_time("2030-01-01T00:00:00Z")
    scheduler.configure(
        {"job_name": "trend", "interval": "00:01:00", "payload": {"trend": ["Topic"]}}
    )
    scheduler.tick()
    assert not calls
    scheduler.set_time("2030-01-01T00:01:01Z")
    scheduler.tick()
    assert calls == ["trend"]
    status = scheduler.status()["active_jobs"][0]
    assert parse_datetime(status["next_trigger"]) >= parse_datetime(
        "2030-01-01T00:02:01Z"
    )
    restored = Scheduler(factory, lambda *args: None)
    assert restored.status()["active_jobs_count"] == 1
    restored.cancel_all()
    assert restored.status()["active_jobs_count"] == 0


def test_scheduler_does_not_repeat_one_shot_or_replay_old_backlog(isolated):
    _, factory = isolated
    calls = []
    scheduler = Scheduler(factory, lambda *args: calls.append(True))
    scheduler.set_time("2030-01-01T00:00:00Z")
    scheduler.configure(
        {"job_name": "trend", "datetimes": ["2030-01-01T00:01:00Z"], "payload": {}}
    )
    scheduler.set_time("2030-01-01T00:01:01Z")
    scheduler.tick()
    scheduler.cooldown_until = 0
    scheduler.tick()
    assert len(calls) == 1
    assert scheduler.status()["active_jobs"][0]["status"] == "COMPLETED"
    scheduler.configure(
        {"job_name": "trend", "datetimes": ["2030-01-01T00:02:00Z"], "payload": {}}
    )
    scheduler.set_time("2030-01-01T00:10:00Z")
    scheduler.tick()
    assert len(calls) == 1
    assert scheduler.status()["active_jobs"][0]["status"] == "EXPIRED"


def test_scheduler_rejects_conflicting_or_empty_triggers(client):
    for payload in [
        {"job_name": "trend"},
        {"job_name": "process", "interval": "00:01:00"},
        {
            "job_name": "trend",
            "interval": "00:01:00",
            "datetimes": ["2030-01-01T00:00:00Z"],
        },
        {
            "job_name": "trend",
            "interval": "00:01:00",
            "start_datetime": "2030-01-02",
            "end_datetime": "2030-01-01",
        },
    ]:
        assert client.post("/schedule", json=payload).status_code == 422


def test_clock_timezone_and_progress(client):
    assert parse_datetime("2030-01-01T03:30:00+03:30") == parse_datetime(
        "2030-01-01T00:00:00Z"
    )
    first = client.post(
        "/update_time", json={"current_time": "2030-01-01T00:00:00Z"}
    ).json()
    main.scheduler._anchor -= 1  # Advance the test clock without a real sleep.
    second = client.get("/current_time").json()
    assert second["simulated"] is True
    assert parse_datetime(second["current_time"]) > parse_datetime(
        first["current_time"]
    )
    assert (
        client.post("/update_time", json={"current_time": None}).json()["simulated"]
        is False
    )


def test_additive_migration_keeps_existing_content(isolated):
    _, factory = isolated
    with main.engine.begin() as connection:
        connection.execute(text("DROP TABLE contents"))
        connection.execute(
            text("""CREATE TABLE contents (id INTEGER PRIMARY KEY, url VARCHAR(2048),
            topic VARCHAR(500), body TEXT NOT NULL, trend BOOLEAN, created_at DATETIME NOT NULL)""")
        )
        connection.execute(
            text(
                "INSERT INTO contents VALUES (1, NULL, 'Original', 'Saved article', 1, '2026-01-01 00:00:00')"
            )
        )
    main.initialize_database()
    main.initialize_database()
    with factory() as db:
        row = db.get(Content, 1)
        assert row.body == "Saved article" and row.wordpress_status == "local"


def test_source_extraction_does_not_duplicate_nested_article():
    html = "<nav>Ignore</nav><main><article><h1>Headline</h1><p>The number is 1982.</p><script>bad()</script></article></main>"
    result = clean_html(html)
    assert result.count("Headline") == 1
    assert "1982" in result and "Ignore" not in result and "bad" not in result


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_private_source_addresses_are_rejected(address, monkeypatch):
    monkeypatch.setattr(
        scraper.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, (address, 80))],
    )
    with pytest.raises(scraper.ScrapeError):
        scraper.validate_public_url("http://source.test/article")


def test_formatting_preserves_facts_and_markdown():
    text = "<think>Private reasoning</think>\n# History\n\nIn 1982: the telescope opened.\n\n- Fact one\n- Fact two"
    result = llm.format_text(text)
    assert "Private reasoning" not in result
    assert "1982:" in result and "# History" in result and "- Fact two" in result


def test_wordpress_html_is_sanitized():
    html = beautify_content(
        "# Title\n\n<script>alert(1)</script>\n\n[Bad](javascript:alert(1))"
    )
    assert "<script" not in html and 'href="javascript:' not in html
    assert "<h1>Title</h1>" in html


def test_runtime_key_cannot_close_script(client, monkeypatch):
    monkeypatch.setattr(main.config, "API_KEY", "</script><script>alert(1)</script>")
    response = client.get("/")
    assert response.status_code == 200
    assert "</script><script>alert(1)</script>" not in response.text
    assert response.headers["cache-control"] == "no-store"


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError("Mock HTTP error")

    def json(self):
        return self.data


def test_local_model_detects_text_model_and_uses_bounded_requests(monkeypatch):
    calls = []

    class Session:
        def __init__(self):
            self.headers = {}
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs["timeout"][0] == 5
            return FakeResponse({"data": [{"id": "embed-test"}, {"id": "story-model"}]})

        def post(self, url, **kwargs):
            calls.append(url)
            assert kwargs["json"]["model"] == "story-model"
            assert kwargs["json"]["max_tokens"] == 100
            assert kwargs["timeout"][1] == llm.config.MODEL_TIMEOUT
            return FakeResponse(
                {"choices": [{"message": {"content": "A concise answer"}}]}
            )

    monkeypatch.setattr(llm.requests, "Session", Session)
    monkeypatch.setattr(llm.config, "MODEL_PROVIDER", "local")
    monkeypatch.setattr(llm.config, "LMSTUDIO_MODEL", "")
    monkeypatch.setattr(llm.config, "LMSTUDIO_API_BASE", "http://model.test/v1")
    assert llm.generate_text("Prompt", max_tokens=100) == "A concise answer"
    assert calls == [
        "http://model.test/v1/models",
        "http://model.test/v1/chat/completions",
    ]


def test_unsupported_chat_endpoint_falls_back_to_completion(monkeypatch):
    calls = []

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append(url)
            if url.endswith("chat/completions"):
                return FakeResponse({}, 404)
            assert kwargs["json"]["prompt"] == "Prompt"
            return FakeResponse({"choices": [{"text": "Completion answer"}]})

    monkeypatch.setattr(llm.requests, "Session", Session)
    monkeypatch.setattr(llm.config, "LMSTUDIO_MODEL", "configured-model")
    monkeypatch.setattr(llm.config, "LMSTUDIO_API_BASE", "http://model.test")
    assert llm.generate_text("Prompt", local_generate=True) == "Completion answer"
    assert calls == [
        "http://model.test/v1/chat/completions",
        "http://model.test/v1/completions",
    ]


def test_hosted_generation_is_explicit_and_requires_token(monkeypatch):
    monkeypatch.setattr(llm.config, "MODEL_PROVIDER", "hf")
    monkeypatch.setattr(llm.config, "HF_TOKEN", "")
    with pytest.raises(llm.ModelUnavailable, match="HF_TOKEN"):
        llm.generate_text("Prompt")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert url == "https://router.huggingface.co/v1/chat/completions"
            assert kwargs["headers"]["Authorization"] == "Bearer mocked-token"
            return FakeResponse(
                {"choices": [{"message": {"content": "Hosted answer"}}]}
            )

    monkeypatch.setattr(llm.requests, "Session", Session)
    monkeypatch.setattr(llm.config, "HF_TOKEN", "mocked-token")
    assert llm.generate_text("Prompt") == "Hosted answer"


def test_reasoning_only_response_is_not_returned_as_an_article():
    with pytest.raises(llm.ModelUnavailable):
        llm._extract(
            {"choices": [{"message": {"content": "<think>unfinished reasoning"}}]}
        )


def test_trend_adapters_match_legacy_and_current_markup(monkeypatch):
    from scraper import trends

    class Response:
        text = "<div class='tileKeyword'>Old topic</div><h3><a href='/topic/new'>New topic</a></h3>"

    monkeypatch.setattr(trends, "make_request", lambda url: Response())
    assert trends.get_trends_from_page() == ["Old topic", "New topic"]
    Response.text = (
        "<h4 class='paid-news'>Hidden paid story</h4><h4>Public headline</h4>"
    )
    assert trends.get_trends_from_trendaz() == ["Public headline"]


def test_scheduler_failure_does_not_kill_future_runs(isolated):
    _, factory = isolated

    def fail(*args):
        raise ValueError("Test failure")

    scheduler = Scheduler(factory, fail)
    scheduler.set_time("2030-01-01T00:00:00Z")
    scheduler.configure({"job_name": "trend", "interval": "00:01:00", "payload": {}})
    scheduler.set_time("2030-01-01T00:01:01Z")
    scheduler.tick()
    row = scheduler.status()["active_jobs"][0]
    assert row["status"] == "SCHEDULED"
    assert row["execution_info"]["error"] == "Test failure"
    assert row["next_trigger"]
    assert not scheduler.run_lock.locked()
