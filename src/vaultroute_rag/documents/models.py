import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vaultroute_rag.database.base import Base, TimestampMixin
from vaultroute_rag.identity.models import Department, Role, User


def new_id() -> str:
    return str(uuid.uuid4())


document_departments = Table(
    "document_departments",
    Base.metadata,
    Column(
        "document_id",
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "department_id",
        String(36),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

document_roles = Table(
    "document_roles",
    Base.metadata,
    Column(
        "document_id",
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("company_id", "checksum", name="uq_document_company_checksum"),
        CheckConstraint(
            "classification IN ('internal', 'confidential', 'restricted')",
            name="ck_document_classification",
        ),
        CheckConstraint("status IN ('processing', 'indexed', 'failed')", name="ck_document_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_company_wide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(160))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    departments: Mapped[list[Department]] = relationship(secondary=document_departments)
    roles: Mapped[list[Role]] = relationship(secondary=document_roles)
    user_permissions: Mapped[list["DocumentUserPermission"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentUserPermission(Base):
    __tablename__ = "document_user_permissions"
    __table_args__ = (
        CheckConstraint("effect IN ('allow', 'deny')", name="ck_document_user_effect"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    effect: Mapped[str] = mapped_column(String(10), nullable=False)

    document: Mapped[Document] = relationship(back_populates="user_permissions")
    user: Mapped[User] = relationship()
