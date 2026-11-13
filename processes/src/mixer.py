# Copyright (c) 2026 Roman Sutormin. MIT License.

"""Combine World-scope metric files into one frontend JSON array.

Reads every JSON file in ``data/``, keeps the documents whose metadata scope
is ``World``, and writes them as a single array to
``frontend/src/world-metrics.json``. Europe-scoped files are left out.
"""

from __future__ import annotations

import json
from pathlib import Path

WORLD_SCOPE = "World"


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "data").is_dir() and (parent / "processes").is_dir():
            return parent
    raise FileNotFoundError(
        "Could not locate the repository root (expected data/ and processes/)."
    )


def load_world_metrics(data_dir: Path) -> list[dict]:
    """Return World-scope documents, ordered by metric key."""
    documents = []
    for path in sorted(data_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        metadata = document.get("metadata") if isinstance(document, dict) else None
        if not isinstance(metadata, dict) or metadata.get("scope") != WORLD_SCOPE:
            continue
        documents.append(document)
    documents.sort(key=lambda document: str(document["metadata"].get("key", "")))
    return documents


def mix(data_dir: Path | None = None, output_path: Path | None = None) -> Path:
    """Write the combined World-scope array and return its path."""
    root = repo_root()
    source = data_dir or root / "data"
    destination = output_path or root / "frontend" / "src" / "world-metrics.json"
    documents = load_world_metrics(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(documents, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    path = mix()
    documents = json.loads(path.read_text(encoding="utf-8"))
    metric_keys = [document["metadata"]["key"] for document in documents]
    print(f"Wrote {len(documents)} World-scope metrics to {path}")
    for key in metric_keys:
        print(f"- {key}")


if __name__ == "__main__":
    main()
