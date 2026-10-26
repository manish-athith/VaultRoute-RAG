from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=12)


class RetrievedEvidence(BaseModel):
    source_id: str
    document_id: str
    document_version: int
    title: str
    source_filename: str
    classification: str
    departments: tuple[str, ...]
    chunk_index: int
    text: str
    semantic_score: float
    lexical_score: float
    final_score: float


class SearchResponse(BaseModel):
    question: str
    evidence: tuple[RetrievedEvidence, ...]
    candidates_considered: int
    max_score: float
    conflict_detected: bool
    warnings: tuple[str, ...] = ()


class RetrievalCandidate(BaseModel):
    """Internal candidate after Qdrant and authoritative permission checks."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_version: int
    title: str
    source_filename: str
    classification: str
    departments: tuple[str, ...]
    chunk_index: int
    text: str
    semantic_score: float
    lexical_score: float
    final_score: float
