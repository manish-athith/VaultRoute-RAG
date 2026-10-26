import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.authorization.evaluator import is_authorized
from vaultroute_rag.documents.embeddings import EmbeddingProvider
from vaultroute_rag.documents.repository import DocumentRepository
from vaultroute_rag.documents.vector_store import QdrantChunkStore
from vaultroute_rag.retrieval.schemas import (
    RetrievalCandidate,
    RetrievedEvidence,
    SearchRequest,
    SearchResponse,
)

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
    }
)


class RetrievalService:
    def __init__(
        self,
        repository: DocumentRepository,
        embeddings: EmbeddingProvider,
        chunk_store: QdrantChunkStore,
        candidate_limit: int,
        default_top_k: int,
        minimum_score: float,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._chunk_store = chunk_store
        self._candidate_limit = candidate_limit
        self._default_top_k = default_top_k
        self._minimum_score = minimum_score

    async def embed_question(self, question: str) -> list[float]:
        return await self._embeddings.embed_query(question)

    async def search(
        self,
        profile: AccessProfile,
        request: SearchRequest,
        query_vector: Sequence[float] | None = None,
    ) -> SearchResponse:
        top_k = request.top_k or self._default_top_k
        if query_vector is None:
            query_vector = await self.embed_question(request.question)
        points = await self._chunk_store.search_authorized(
            profile=profile,
            query_vector=query_vector,
            limit=max(self._candidate_limit, top_k * 3),
            score_threshold=self._minimum_score,
        )
        document_ids = {
            str(point.payload.get("document_id"))
            for point in points
            if point.payload and point.payload.get("document_id")
        }
        documents = {
            document.id: document
            for document in await self._repository.get_by_ids(profile.company_id, document_ids)
        }

        query_terms = self._terms(request.question)
        candidates: list[RetrievalCandidate] = []
        for point in points:
            payload = point.payload or {}
            document = documents.get(str(payload.get("document_id", "")))
            if document is None or document.status != "indexed":
                continue
            if int(payload.get("document_version", 0)) != document.version:
                continue
            if not is_authorized(profile, self._repository.access_rule(document)):
                continue

            text = str(payload.get("chunk_text", "")).strip()
            if not text:
                continue
            semantic_score = max(0.0, min(1.0, float(point.score)))
            lexical_score = self._lexical_score(query_terms, text)
            final_score = (semantic_score * 0.85) + (lexical_score * 0.15)
            candidates.append(
                RetrievalCandidate(
                    document_id=document.id,
                    document_version=document.version,
                    title=document.title,
                    source_filename=document.source_filename,
                    classification=document.classification,
                    departments=tuple(sorted(item.code for item in document.departments)),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    text=text,
                    semantic_score=round(semantic_score, 4),
                    lexical_score=round(lexical_score, 4),
                    final_score=round(final_score, 4),
                )
            )

        current, warnings, conflict_detected = self._resolve_versions(candidates)
        ranked = self._diversify(current, top_k)
        evidence = tuple(
            RetrievedEvidence(source_id=f"S{index}", **candidate.model_dump())
            for index, candidate in enumerate(ranked, start=1)
        )
        return SearchResponse(
            question=request.question,
            evidence=evidence,
            candidates_considered=len(points),
            max_score=max((item.final_score for item in evidence), default=0.0),
            conflict_detected=conflict_detected,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {
            term
            for term in re.findall(r"[a-z0-9]+", text.lower())
            if len(term) > 1 and term not in STOP_WORDS
        }

    @classmethod
    def _lexical_score(cls, query_terms: set[str], text: str) -> float:
        if not query_terms:
            return 0.0
        text_terms = cls._terms(text)
        return len(query_terms.intersection(text_terms)) / len(query_terms)

    @staticmethod
    def _title_key(title: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", title.lower()))

    @classmethod
    def _resolve_versions(
        cls, candidates: list[RetrievalCandidate]
    ) -> tuple[list[RetrievalCandidate], list[str], bool]:
        versions: dict[str, set[tuple[str, int]]] = defaultdict(set)
        for item in candidates:
            versions[cls._title_key(item.title)].add((item.document_id, item.document_version))

        current_versions = {
            title: max(version for _, version in identities)
            for title, identities in versions.items()
        }
        warnings: list[str] = []
        conflict_detected = False
        for title, identities in versions.items():
            if len(identities) > 1:
                conflict_detected = True
                warnings.append(
                    f"Multiple documents share the title '{title}'; older versions were removed "
                    "and same-version sources were kept for comparison."
                )

        current = [
            item
            for item in candidates
            if item.document_version == current_versions[cls._title_key(item.title)]
        ]
        return current, warnings, conflict_detected

    @staticmethod
    def _diversify(candidates: list[RetrievalCandidate], top_k: int) -> list[RetrievalCandidate]:
        per_document: Counter[str] = Counter()
        selected: list[RetrievalCandidate] = []
        for item in sorted(candidates, key=lambda candidate: candidate.final_score, reverse=True):
            if per_document[item.document_id] >= 2:
                continue
            selected.append(item)
            per_document[item.document_id] += 1
            if len(selected) == top_k:
                break
        return selected
