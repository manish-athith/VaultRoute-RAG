import re

from vaultroute_rag.generation.providers import TextModelProvider
from vaultroute_rag.generation.schemas import RouteDecision
from vaultroute_rag.retrieval.schemas import SearchResponse

COMPLEX_TERMS = frozenset(
    {
        "analyze",
        "compare",
        "conflict",
        "contradict",
        "difference",
        "explain why",
        "implications",
        "recommend",
        "risks",
        "strategy",
        "tradeoff",
    }
)


class NoModelProviderAvailable(RuntimeError):
    """Raised when neither configured provider can serve a request."""


class ModelRouter:
    def __init__(self, small: TextModelProvider, large: TextModelProvider) -> None:
        self.small = small
        self.large = large

    def choose(
        self, question: str, retrieval: SearchResponse
    ) -> tuple[TextModelProvider, RouteDecision]:
        lowered = question.lower()
        complexity = 0
        reasons: list[str] = []
        if len(re.findall(r"\S+", question)) >= 28:
            complexity += 1
            reasons.append("long question")
        if any(term in lowered for term in COMPLEX_TERMS):
            complexity += 1
            reasons.append("analysis language")
        if len(retrieval.evidence) >= 4:
            complexity += 1
            reasons.append("multiple sources")
        if retrieval.conflict_detected:
            complexity += 2
            reasons.append("source conflict")
        if retrieval.max_score < 0.55:
            complexity += 1
            reasons.append("weaker evidence")

        preferred = self.large if complexity >= 2 else self.small
        fallback = self.small if preferred is self.large else self.large
        route_name = "large" if preferred is self.large else "small"
        if preferred.available:
            provider = preferred
            reason = f"{route_name} route: {', '.join(reasons) or 'simple focused question'}"
        elif fallback.available:
            provider = fallback
            reason = f"{route_name} provider unavailable; used configured fallback"
        else:
            raise NoModelProviderAvailable(
                "No model provider is configured; add GROQ_API_KEY or OPENAI_API_KEY"
            )
        return provider, RouteDecision(
            provider=provider.provider_name,
            model=provider.model_name,
            reason=reason,
        )
