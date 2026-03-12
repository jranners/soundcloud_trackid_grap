import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tracklist(Base):
    __tablename__ = "tracklists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    tracks = relationship("Track", back_populates="tracklist", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracklist_id = Column(UUID(as_uuid=True), ForeignKey("tracklists.id"), nullable=False)
    title = Column(String, nullable=True)
    artist = Column(String, nullable=True)
    timestamp_start = Column(Float, nullable=False)
    timestamp_end = Column(Float, nullable=True)
    snippet_path = Column(String, nullable=True)
    raw_result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    tracklist = relationship("Tracklist", back_populates="tracks")
