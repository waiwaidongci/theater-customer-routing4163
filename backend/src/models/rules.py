from datetime import datetime
from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.utils.time import now

class RuleVersion(Base):
    __tablename__ = 'rule_versions'
    __table_args__ = (UniqueConstraint('effective_at', 'issued_seq', name='uq_rule_moment_seq'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    effective_at: Mapped[datetime] = mapped_column(index=True)
    issued_seq: Mapped[int]
    params: Mapped[dict] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
