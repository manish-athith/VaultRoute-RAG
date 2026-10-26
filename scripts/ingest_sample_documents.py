import asyncio
import json
import os
from pathlib import Path

import httpx

from vaultroute_rag.core.config import get_settings

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "data" / "sample_documents"


async def ingest_samples() -> None:
    settings = get_settings()
    base_url = os.getenv("VAULTROUTE_API_URL", "http://localhost:8000").rstrip("/")
    manifest = json.loads((SAMPLE_ROOT / "manifest.json").read_text(encoding="utf-8"))

    async with httpx.AsyncClient(base_url=base_url, timeout=180) as client:
        login = await client.post(
            "/auth/login",
            json={
                "company_slug": "acme",
                "email": "ceo@acme.example.com",
                "password": settings.seed_user_password,
            },
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        indexed = 0
        skipped = 0
        for item in manifest:
            path = SAMPLE_ROOT / item["path"]
            access = {
                "classification": item["classification"],
                "department_codes": item["department_codes"],
            }
            response = await client.post(
                "/documents/upload",
                headers=headers,
                data={"title": item["title"], "access_json": json.dumps(access)},
                files={"file": (path.name, path.read_bytes(), "text/markdown")},
            )
            if response.status_code == 409:
                skipped += 1
                continue
            response.raise_for_status()
            indexed += 1
            result = response.json()
            print(f"Indexed {result['title']} ({result['chunk_count']} chunks)")

        print(f"Sample ingestion complete: indexed={indexed}, already_present={skipped}")


if __name__ == "__main__":
    asyncio.run(ingest_samples())
