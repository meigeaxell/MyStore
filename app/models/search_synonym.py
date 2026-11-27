from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class SearchSynonym(Base):
    """Пользовательский словарь синонимов и сокращений для поиска и Guty OCR.

    Пример:
      term = "udarnyk" -> expansions = "glass, стекло, aýna, защитное"
      term = "16pm"    -> expansions = "iphone 16 pro max"
    """

    __tablename__ = "search_synonyms"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    expansions: Mapped[str] = mapped_column(
        String(400),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )
