import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from vaultroute_rag.core.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = PROJECT_ROOT / "data" / "evaluation" / "rag_cases.json"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "rag_evaluation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeatable retrieval and access-safety checks against VaultRoute RAG."
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--company", default="acme")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--minimum-top1", type=float, default=0.80)
    parser.add_argument("--minimum-access-safety", type=float, default=1.0)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation cases must be a non-empty JSON list")
    return cases


async def login(
    client: httpx.AsyncClient,
    *,
    company: str,
    email: str,
    password: str,
) -> str:
    response = await client.post(
        "/auth/login",
        json={"company_slug": company, "email": email, "password": password},
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def score_case(case: dict[str, Any], payload: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    evidence = payload.get("evidence", [])
    top_title = evidence[0]["title"] if evidence else None
    expected_title = case.get("expected_top_title")
    relevance_scored = expected_title is not None
    top1_correct = top_title == expected_title if relevance_scored else None

    allowed = set(case["allowed_departments"])
    returned_departments = sorted(
        {department for item in evidence for department in item.get("departments", [])}
    )
    access_safe = set(returned_departments).issubset(allowed)

    return {
        "id": case["id"],
        "email": case["email"],
        "expected_top_title": expected_title,
        "actual_top_title": top_title,
        "top1_correct": top1_correct,
        "access_safe": access_safe,
        "allowed_departments": sorted(allowed),
        "returned_departments": returned_departments,
        "max_score": round(float(payload.get("max_score", 0)), 4),
        "evidence_count": len(evidence),
        "response_ms": round(elapsed_ms, 2),
    }


async def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    cases = load_cases(args.cases)
    tokens: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=180) as client:
        for case in cases:
            email = str(case["email"])
            if email not in tokens:
                tokens[email] = await login(
                    client,
                    company=args.company,
                    email=email,
                    password=settings.seed_user_password,
                )

            started = perf_counter()
            response = await client.post(
                "/search",
                headers={"Authorization": f"Bearer {tokens[email]}"},
                json={"question": case["question"], "top_k": args.top_k},
            )
            elapsed_ms = (perf_counter() - started) * 1000
            response.raise_for_status()
            results.append(score_case(case, response.json(), elapsed_ms))

    relevance_results = [item for item in results if item["top1_correct"] is not None]
    top1_accuracy = sum(bool(item["top1_correct"]) for item in relevance_results) / len(
        relevance_results
    )
    access_safety_rate = sum(bool(item["access_safe"]) for item in results) / len(results)
    average_response_ms = sum(float(item["response_ms"]) for item in results) / len(results)
    passed = top1_accuracy >= args.minimum_top1 and access_safety_rate >= args.minimum_access_safety

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "dataset": str(args.cases),
        "summary": {
            "cases": len(results),
            "relevance_cases": len(relevance_results),
            "top1_accuracy": round(top1_accuracy, 4),
            "access_safety_rate": round(access_safety_rate, 4),
            "average_response_ms": round(average_response_ms, 2),
            "minimum_top1": args.minimum_top1,
            "minimum_access_safety": args.minimum_access_safety,
            "passed": passed,
        },
        "cases": results,
    }


async def main() -> int:
    args = parse_args()
    report = await run_evaluation(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output.resolve()}")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
