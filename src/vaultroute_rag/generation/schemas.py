from pydantic import BaseModel, ConfigDict, Field

from vaultroute_rag.retrieval.schemas import SearchResponse


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=12)


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ModelResult(BaseModel):
    text: str
    provider: str
    model: str
    usage: ModelUsage = Field(default_factory=ModelUsage)


class RouteDecision(BaseModel):
    provider: str
    model: str
    reason: str


class AnswerCitation(BaseModel):
    source_id: str
    document_id: str
    document_version: int
    title: str
    source_filename: str
    departments: tuple[str, ...]
    excerpt: str


class AnswerResponse(BaseModel):
    query_id: str | None = None
    question: str
    answer: str
    citations: tuple[AnswerCitation, ...]
    route: RouteDecision
    usage: ModelUsage
    retrieval: SearchResponse
    cache_hit: bool = False
    cache_similarity: float | None = None
