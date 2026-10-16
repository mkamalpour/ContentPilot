"""Durable schedules, a progressing test clock, and strictly serial execution."""

from datetime import datetime, timedelta, timezone
import json
import logging
import re
import threading
import time
import uuid
from database.models import ScheduledJob

logger = logging.getLogger(__name__)
UTC = timezone.utc


def parse_datetime(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (
        result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
    )


def interval_seconds(value):
    if not value or value == "00:00:00":
        return None
    if not re.fullmatch(r"\d{1,4}:\d{2}:\d{2}", value):
        raise ValueError("Use HH:MM:SS for the interval")
    hours, minutes, seconds = map(int, value.split(":"))
    if minutes > 59 or seconds > 59:
        raise ValueError("Minutes and seconds must be between 00 and 59")
    result = hours * 3600 + minutes * 60 + seconds
    if result < 5:
        raise ValueError("The minimum interval is five seconds")
    return result


class Scheduler:
    def __init__(self, session_factory, callback):
        self.session_factory, self.callback = session_factory, callback
        self.lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.abort = threading.Event()
        self.stop_event = threading.Event()
        self.thread = None
        self.running = None
        self._clock = None
        self._anchor = 0
        self.cooldown_until = 0

    def now(self):
        with self.lock:
            return (
                self._clock + timedelta(seconds=time.monotonic() - self._anchor)
                if self._clock
                else datetime.now(UTC)
            )

    def set_time(self, value):
        with self.lock:
            if self.run_lock.locked():
                raise ValueError(
                    "Wait for the current operation before changing the clock"
                )
            self._clock = parse_datetime(value) if value else None
            self._anchor = time.monotonic()
        return self.clock_status()

    def clock_status(self):
        return {
            "current_time": self.now().isoformat(),
            "simulated": self._clock is not None,
            "simulated_time": self._clock.isoformat() if self._clock else None,
        }

    def configure(self, request):
        name = request["job_name"]
        if name not in {"trend", "process", "all"}:
            raise ValueError("Unknown job type")
        enabled = request.get("enabled", True)
        seconds = interval_seconds(request.get("interval")) if enabled else None
        times = sorted(
            set(
                parse_datetime(value).isoformat()
                for value in (request.get("datetimes") or [])
            )
        )
        start = (
            parse_datetime(request["start_datetime"])
            if request.get("start_datetime")
            else None
        )
        end = (
            parse_datetime(request["end_datetime"])
            if request.get("end_datetime")
            else None
        )
        if start and end and start >= end:
            raise ValueError("The schedule end must follow its start")
        if seconds and times:
            raise ValueError("Choose either an interval or specific dates")
        if enabled and not seconds and not times:
            raise ValueError("Choose an interval or at least one future date")
        now = self.now()
        if enabled and end and end <= now:
            raise ValueError("The schedule window has already ended")
        if enabled and times and any(parse_datetime(value) <= now for value in times):
            raise ValueError("Scheduled dates must be in the future")
        times = [
            value
            for value in times
            if (not start or parse_datetime(value) >= start)
            and (not end or parse_datetime(value) <= end)
        ]
        if enabled and not seconds and not times:
            raise ValueError("No dates fall inside the selected window")
        next_run = (
            max(now + timedelta(seconds=seconds), start or now)
            if seconds
            else (parse_datetime(times[0]) if times else None)
        )
        if enabled and end and next_run and next_run > end:
            raise ValueError("The first run falls after the schedule window")
        data = {
            "interval": seconds,
            "datetimes": times,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "payload": request.get("payload", {}),
            "revision": uuid.uuid4().hex,
        }
        with self.lock, self.session_factory() as db:
            row = db.get(ScheduledJob, name) or ScheduledJob(job_name=name)
            row.config = json.dumps(data)
            row.next_run = next_run.isoformat() if enabled and next_run else None
            row.status = "SCHEDULED" if enabled else "CANCELED"
            row.last_error = ""
            db.add(row)
            db.commit()
        logger.info(
            "Automation %s: task=%s next_run=%s",
            "scheduled" if enabled else "canceled",
            name,
            row.next_run,
        )
        return {"status": "scheduled" if enabled else "canceled"}

    def cancel_all(self):
        with self.lock, self.session_factory() as db:
            for row in db.query(ScheduledJob).all():
                row.status, row.next_run = "CANCELED", None
            db.commit()
            self.abort.set()
        logger.info("All automations canceled")
        return {
            "status": "canceled",
            "message": "Schedules canceled. In-flight requests finish before their result is discarded.",
        }

    def status(self):
        now = self.now()
        with self.lock, self.session_factory() as db:
            rows = db.query(ScheduledJob).order_by(ScheduledJob.job_name).all()
            jobs = []
            for row in rows:
                data = json.loads(row.config)
                jobs.append(
                    {
                        "job_name": row.job_name,
                        "status": row.status,
                        "interval": data.get("interval"),
                        "next_trigger": row.next_run,
                        "waiting_for": ["An operation is already running"]
                        if self.running and self.running != row.job_name
                        else [],
                        "execution_info": {
                            "last_run": row.last_run,
                            "error": row.last_error,
                        },
                        "datetimes": data.get("datetimes", []),
                        "start": data.get("start"),
                        "end": data.get("end"),
                    }
                )
            return {
                "active_jobs_count": sum(
                    row.status in {"SCHEDULED", "RUNNING"} for row in rows
                ),
                "active_jobs": jobs,
                "current_time": now.isoformat(),
                "is_busy": self.run_lock.locked(),
            }

    def tick(self):
        if (
            self.stop_event.is_set()
            or time.monotonic() < self.cooldown_until
            or not self.run_lock.acquire(blocking=False)
        ):
            return
        selected = None
        try:
            now = self.now()
            with self.lock, self.session_factory() as db:
                rows = (
                    db.query(ScheduledJob)
                    .filter(ScheduledJob.status == "SCHEDULED")
                    .all()
                )
                for row in sorted(rows, key=lambda item: item.next_run or "9999"):
                    data = json.loads(row.config)
                    if data.get("end") and now > parse_datetime(data["end"]):
                        row.status, row.next_run = "EXPIRED", None
                        continue
                    if not row.next_run or parse_datetime(row.next_run) > now:
                        continue
                    # A stopped application must not replay a backlog of one-shot jobs.
                    if (
                        not data.get("interval")
                        and (now - parse_datetime(row.next_run)).total_seconds() > 60
                    ):
                        upcoming = [
                            value
                            for value in data["datetimes"]
                            if parse_datetime(value) > now
                        ]
                        row.next_run = upcoming[0] if upcoming else None
                        row.status = "SCHEDULED" if upcoming else "EXPIRED"
                        continue
                    row.status, row.last_run, row.last_error = (
                        "RUNNING",
                        now.isoformat(),
                        "",
                    )
                    self.running = row.job_name
                    self.abort.clear()
                    selected = (row.job_name, data)
                    break
                db.commit()
            if selected is None:
                return
            name, data = selected
            logger.info("Automation started: task=%s", name)
            error = ""
            try:
                self.callback(name, data["payload"], self.abort)
            except Exception as exc:
                error = str(exc)[:400]
                logger.warning("Scheduled %s failed: %s", name, type(exc).__name__)
            finished = self.now()
            with self.lock, self.session_factory() as db:
                row = db.get(ScheduledJob, name)
                # A cancel or edit during generation must win over completion.
                if (
                    row
                    and row.status != "CANCELED"
                    and json.loads(row.config).get("revision") == data["revision"]
                ):
                    future = [
                        value
                        for value in data["datetimes"]
                        if parse_datetime(value) > finished
                    ]
                    next_run = (
                        finished + timedelta(seconds=data["interval"])
                        if data.get("interval")
                        else (parse_datetime(future[0]) if future else None)
                    )
                    if (
                        data.get("end")
                        and next_run
                        and next_run > parse_datetime(data["end"])
                    ):
                        next_run = None
                    row.next_run = next_run.isoformat() if next_run else None
                    row.last_error = error
                    row.status = (
                        "SCHEDULED"
                        if next_run
                        else ("FAILED" if error else "COMPLETED")
                    )
                    db.commit()
                    logger.info(
                        "Automation finished: task=%s status=%s", name, row.status
                    )
        finally:
            if selected:
                self.cooldown_until = time.monotonic() + 5
            self.running = None
            self.run_lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        with self.session_factory() as db:
            for row in (
                db.query(ScheduledJob).filter(ScheduledJob.status == "RUNNING").all()
            ):
                row.status, row.next_run = "FAILED", None
                row.last_error = "Interrupted during the previous application run. Review and re-enable this schedule."
            db.commit()
        self.stop_event.clear()

        def loop():
            while not self.stop_event.wait(0.5):
                try:
                    self.tick()
                except Exception:
                    logger.exception("Scheduler tick failed")

        self.thread = threading.Thread(
            target=loop, name="contentpilot-scheduler", daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.abort.set()
        if self.thread:
            self.thread.join(timeout=2)
