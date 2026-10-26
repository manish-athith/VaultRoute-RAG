from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentClassification(StrEnum):
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentAccessInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    classification: DocumentClassification = DocumentClassification.INTERNAL
    department_codes: tuple[str, ...] = Field(default=(), max_length=20)
    role_codes: tuple[str, ...] = Field(default=(), max_length=20)
    allowed_user_emails: tuple[str, ...] = Field(default=(), max_length=50)
    denied_user_emails: tuple[str, ...] = Field(default=(), max_length=50)
    is_company_wide: bool = False

    @field_validator("department_codes", "role_codes", "allowed_user_emails", "denied_user_emails")
    @classmethod
    def normalize_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({value.strip().lower() for value in values if value.strip()}))

    @model_validator(mode="after")
    def validate_rules(self) -> "DocumentAccessInput":
        overlap = set(self.allowed_user_emails).intersection(self.denied_user_emails)
        if overlap:
            raise ValueError("A user cannot be both explicitly allowed and denied")
        if not (
            self.is_company_wide
            or self.department_codes
            or self.role_codes
            or self.allowed_user_emails
        ):
            raise ValueError("At least one allow rule is required")
        return self


class DocumentResponse(BaseModel):
    id: str
    title: str
    source_filename: str
    media_type: str
    classification: str
    status: str
    version: int
    is_company_wide: bool
    departments: tuple[str, ...]
    roles: tuple[str, ...]
    allowed_users: tuple[str, ...]
    denied_users: tuple[str, ...]
    text_length: int
    chunk_count: int
    embedding_model: str | None
    created_at: datetime
    indexed_at: datetime | None


class TextChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    text: str
    word_count: int
    char_start: int
    char_end: int
