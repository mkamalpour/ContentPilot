"""Content and durable automation configuration (existing content schema preserved)."""

from datetime import datetime, timezone
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean

Base = declarative_base()


class Content(Base):
    __tablename__ = "contents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), nullable=True)
    topic = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    trend = Column(Boolean, nullable=True, default=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    wordpress_id = Column(Integer, nullable=True)
    wordpress_status = Column(String(30), nullable=False, default="local")

    def to_dict(self):
        created = (
            self.created_at.replace(tzinfo=timezone.utc).isoformat()
            if self.created_at
            else None
        )
        return {
            "id": self.id,
            "url": self.url or "",
            "topic": self.topic or "",
            "body": self.body,
            "trend": bool(self.trend),
            "created_at": created,
            "wordpress_id": self.wordpress_id,
            "wordpress_status": self.wordpress_status,
        }


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    job_name = Column(String(30), primary_key=True)
    config = Column(Text, nullable=False)
    next_run = Column(String(50), nullable=True)
    status = Column(String(30), nullable=False, default="SCHEDULED")
    last_run = Column(String(50), nullable=True)
    last_error = Column(Text, nullable=False, default="")
