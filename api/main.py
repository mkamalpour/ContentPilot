"""ContentPilot API: explicit generation, durable automation and reviewed delivery."""

from contextlib import asynccontextmanager
from hmac import compare_digest
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import random
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import inspect, text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core import config
from core.llm import generate_text, ModelUnavailable
from core.scheduler import Scheduler
from database.connection import engine, SessionLocal
from database.models import Base, Content
from database.publishing import publish_content, wordpress_configured
from analyzer.analyzer import analyze_topic
from generator.generator import generate_content
from scraper.scraper import scrape_url, ScrapeError, validate_url
from scraper.trends import get_trends, get_trend_from_source

logger = logging.getLogger(__name__)


def initialize_database():
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("contents")}
    with engine.begin() as connection:
        if "wordpress_id" not in columns:
            connection.execute(
                text("ALTER TABLE contents ADD COLUMN wordpress_id INTEGER")
            )
        if "wordpress_status" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE contents ADD COLUMN wordpress_status VARCHAR(30) NOT NULL DEFAULT 'local'"
                )
            )


def setup_logging():
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(getattr(handler, "contentpilot", False) for handler in root.handlers):
        return
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        config.LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    handler.contentpilot = True
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)


def check_canceled(abort):
    if abort.is_set():
        raise HTTPException(
            status_code=409,
            detail="Operation canceled; generated results were discarded",
        )


def create_draft(db, *, url=None, topic=None, source="explodingtopics", abort):
    excerpt = None
    if url:
        excerpt = scrape_url(str(url))
        check_canceled(abort)
        topic = analyze_topic(excerpt)
    else:
        topic = topic or get_trend_from_source(source)
    if not topic:
        raise ValueError("No topic was available")
    check_canceled(abort)
    body = generate_content(topic, source_text=excerpt, source_url=url)
    if not isinstance(body, str) or not body.strip():
        raise ModelUnavailable("The model returned no article")
    record = Content(
        url=str(url) if url else None, topic=topic, body=body, trend=not bool(url)
    )
    with scheduler.lock:
        check_canceled(abort)
        db.add(record)
        db.commit()
        db.refresh(record)
    logger.info("Draft saved: id=%s source=%s", record.id, "url" if url else "topic")
    result = record.to_dict()
    if config.WORDPRESS_AUTO_PUBLISH and wordpress_configured():
        try:
            check_canceled(abort)
            delivery = publish_content(record, config.WORDPRESS_DEFAULT_STATUS)
            record.wordpress_id, record.wordpress_status = (
                delivery["id"],
                delivery["status"],
            )
            db.commit()
            result.update(record.to_dict())
        except Exception:
            logger.warning(
                "Automatic WordPress delivery failed; content %s remains saved locally",
                record.id,
            )
            result["publication_error"] = (
                "Draft saved locally; WordPress delivery failed. Review it before retrying."
            )
    return result


def execute_job(name, payload, abort):
    urls = [value for value in payload.get("url", []) if value]
    topics = [value for value in payload.get("trend", []) if value]
    kind = (
        random.choice(["process", "trend"])
        if name == "all" and urls
        else ("trend" if name == "all" else name)
    )
    with SessionLocal() as db:
        return create_draft(
            db,
            url=random.choice(urls) if kind == "process" and urls else None,
            topic=random.choice(topics) if topics else None,
            source=payload.get("source", "explodingtopics"),
            abort=abort,
        )


scheduler = Scheduler(SessionLocal, execute_job)


@asynccontextmanager
async def lifespan(app):
    setup_logging()
    initialize_database()
    if config.SCHEDULER_ENABLED:
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="ContentPilot",
    version="1.0.0",
    description="Source-grounded AI drafting and durable editorial automations.",
    lifespan=lifespan,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(
        {
            "127.0.0.1",
            "localhost",
            "::1",
            "testserver",
            os.getenv("CONTENT_AGENT_HOST", "127.0.0.1"),
        }
    ),
)
app.mount(
    "/static", StaticFiles(directory=config.ROOT / "templates/static"), name="static"
)


@app.middleware("http")
async def protect_api(request, call_next):
    path = request.url.path
    public = path in {"/", "/health", "/favicon.ico"} or path.startswith("/static/")
    if (
        not public
        and config.API_KEY
        and not compare_digest(
            request.headers.get("X-API-Key", "").encode(), config.API_KEY.encode()
        )
    ):
        return JSONResponse({"detail": "Invalid API key"}, status_code=401)
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and origin
        and urlsplit(origin).netloc != request.url.netloc
    ):
        return JSONResponse(
            {"detail": "Cross-origin writes are disabled"}, status_code=403
        )
    return await call_next(request)


@app.exception_handler(ModelUnavailable)
async def model_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(ScrapeError)
async def source_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class URLRequest(InputModel):
    url: HttpUrl


class TrendRequest(InputModel):
    trend: str = Field(default="", max_length=500)
    source: Literal["all", "explodingtopics", "trendaz"] = "explodingtopics"


class JobPayload(InputModel):
    url: list[HttpUrl] = Field(default_factory=list, max_length=20)
    trend: list[str] = Field(default_factory=list, max_length=20)
    source: Literal["all", "explodingtopics", "trendaz"] = "explodingtopics"


class ScheduleRequest(InputModel):
    job_name: Literal["all", "trend", "process"] = "trend"
    interval: str | None = Field(default=None, max_length=20)
    datetimes: list[str] | None = Field(default=None, max_length=100)
    start_datetime: str | None = None
    end_datetime: str | None = None
    enabled: bool = True
    payload: JobPayload = Field(default_factory=JobPayload)
    current_time: str | None = None


class TimeUpdate(InputModel):
    current_time: str | None = None


class ChatRequest(InputModel):
    message: str = Field(min_length=1, max_length=16000)


class PublishRequest(InputModel):
    status: Literal["draft", "publish"] = "draft"


def get_db():
    with SessionLocal() as db:
        yield db


def exclusive_operation():
    if not scheduler.run_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="An operation is already running. Please wait."
        )
    scheduler.abort.clear()
    try:
        yield scheduler.abort
    finally:
        scheduler.run_lock.release()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    local = request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
    runtime = (
        json.dumps({"apiKey": config.API_KEY if local else ""})
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    html = (config.ROOT / "templates/index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html.replace("__CONTENTPILOT_RUNTIME_CONFIG__", runtime),
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@app.get("/health")
def health():
    from core.llm import configuration_readiness
    return {
        "status": "ok",
        "model_provider": config.MODEL_PROVIDER,
        "model_name": config.HF_MODEL
        if config.MODEL_PROVIDER == "hf"
        else config.LMSTUDIO_MODEL or "Auto-detect",
        "wordpress_configured": wordpress_configured(),
        "auto_publish": config.WORDPRESS_AUTO_PUBLISH,
        'readiness': configuration_readiness(),
    }


@app.post("/process")
def process_url(
    req: URLRequest, db=Depends(get_db), abort=Depends(exclusive_operation)
):
    return create_draft(db, url=str(req.url), abort=abort)


@app.post("/generate_by_trend")
def generate_by_trend(
    req: TrendRequest, db=Depends(get_db), abort=Depends(exclusive_operation)
):
    return create_draft(db, topic=req.trend, source=req.source, abort=abort)


@app.get("/trends")
def list_trends(
    source: Literal["all", "explodingtopics", "trendaz"] = "explodingtopics",
):
    return {"trends": get_trends(num_trends=10, source=source)}


@app.get("/contents")
def list_contents(
    db=Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return [
        record.to_dict()
        for record in db.query(Content)
        .order_by(Content.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    ]


@app.get("/contents/{content_id}")
def get_content(content_id: int, db=Depends(get_db)):
    row = db.get(Content, content_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return row.to_dict()


@app.delete("/contents/{content_id}")
def delete_content(
    content_id: int, db=Depends(get_db), abort=Depends(exclusive_operation)
):
    row = db.get(Content, content_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Content not found")
    db.delete(row)
    db.commit()
    return {"deleted": content_id}


@app.delete("/flush_db")
def flush_db(db=Depends(get_db), abort=Depends(exclusive_operation)):
    count = db.query(Content).delete()
    db.commit()
    return {"deleted": count}


@app.post("/contents/{content_id}/publish")
def deliver_content(
    content_id: int,
    req: PublishRequest,
    db=Depends(get_db),
    abort=Depends(exclusive_operation),
):
    record = db.get(Content, content_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Content not found")
    try:
        result = publish_content(record, req.status)
        record.wordpress_id, record.wordpress_status = result["id"], result["status"]
        db.commit()
        logger.info(
            "WordPress delivery completed: content=%s status=%s",
            content_id,
            result["status"],
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("WordPress delivery failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="WordPress delivery failed. Check the connection and application password.",
        ) from exc


@app.post("/chat")
def chat_endpoint(req: ChatRequest, abort=Depends(exclusive_operation)):
    reply = generate_text(req.message)
    check_canceled(abort)
    return {"reply": reply}


@app.post("/schedule")
def schedule(req: ScheduleRequest):
    data = req.model_dump(mode="json")
    if req.enabled and req.job_name == "process" and not req.payload.url:
        raise HTTPException(
            status_code=422, detail="URL schedules need at least one source URL"
        )
    try:
        return scheduler.configure(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/job_status")
@app.get("/scheduler_debug", include_in_schema=False)
def job_status():
    return scheduler.status()


@app.post("/cancel_all_jobs")
def cancel_all_jobs():
    return scheduler.cancel_all()


@app.get("/current_time")
def current_time():
    return scheduler.clock_status()


@app.post("/update_time")
def update_time(req: TimeUpdate):
    try:
        return scheduler.set_time(req.current_time)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/logs")
def logs(from_line: int = Query(0, ge=0), max_lines: int = Query(100, ge=1, le=200)):
    if not config.LOG_PATH.exists():
        return {"lines": [], "total_lines": 0, "next_line": 0}
    lines = config.LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    start = from_line if from_line <= len(lines) else 0
    selected = lines[start : start + max_lines]
    return {
        "lines": selected,
        "total_lines": len(lines),
        "next_line": start + len(selected),
    }
