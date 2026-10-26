import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def postgres_backup(target: Path) -> None:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "vaultroute",
        "-d",
        "vaultroute",
        "--format=custom",
        "--no-owner",
    ]
    with target.open("wb") as output:
        subprocess.run(command, stdout=output, check=True)


def qdrant_backup(base_url: str, collection: str, target: Path) -> None:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120) as client:
        created = client.post(f"/collections/{collection}/snapshots")
        created.raise_for_status()
        snapshot_name = created.json()["result"]["name"]
        download = client.get(f"/collections/{collection}/snapshots/{snapshot_name}")
        download.raise_for_status()
        target.write_bytes(download.content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up VaultRoute PostgreSQL and Qdrant data.")
    parser.add_argument("--output-root", type=Path, default=Path("backups"))
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_root.resolve() / stamp
    destination.mkdir(parents=True, exist_ok=False)
    files = {
        "postgres": destination / "postgres.dump",
        "document_chunks": destination / "document_chunks.snapshot",
        "semantic_answer_cache": destination / "semantic_answer_cache.snapshot",
    }

    postgres_backup(files["postgres"])
    qdrant_backup(args.qdrant_url, "document_chunks", files["document_chunks"])
    qdrant_backup(args.qdrant_url, "semantic_answer_cache", files["semantic_answer_cache"])

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "format": "VaultRoute backup v1",
        "files": {
            name: {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in files.items()
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Backup completed: {destination}")


if __name__ == "__main__":
    main()
