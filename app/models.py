from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeenVacancy(Base):
    __tablename__ = "seen_vacancies"

    uid: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String)
    link: Mapped[str] = mapped_column(String)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class SourceState(Base):
    __tablename__ = "source_state"

    url: Mapped[str] = mapped_column(String, primary_key=True)
    etag: Mapped[str | None] = mapped_column(String, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class LearnedSelector(Base):
    __tablename__ = "learned_selectors"

    url: Mapped[str] = mapped_column(String, primary_key=True)
    item_selector: Mapped[str] = mapped_column(String)
    title_selector: Mapped[str] = mapped_column(String)
    link_selector: Mapped[str] = mapped_column(String)
    location_selector: Mapped[str | None] = mapped_column(String, nullable=True)
    stable_count: Mapped[int] = mapped_column(Integer, default=1)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
