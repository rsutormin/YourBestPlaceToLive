# Copyright (c) 2026 Roman Sutormin. MIT License.

"""Import V-Dem liberal democracy scores into frontend JSON.

Downloads the Country-Year Core dataset and keeps each country's liberal
democracy index. The published index runs from 0 to 1; the stored value is
that index scaled to 0 to 100. The dataset is CC BY-SA 4.0.
"""

from __future__ import annotations

import io
import json
import math
import re
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_START_YEAR = 2020
DATASET_URL = "https://www.v-dem.net/media/datasets/V-Dem-CY-Core-v16_csv.zip"
DATASET_PAGE = "https://v-dem.net/data/the-v-dem-dataset/"
USER_AGENT = "YourBestPlaceToLive/0.1 (V-Dem data import)"
ISO3 = re.compile(r"^[A-Z]{3}$")
SCORE_COLUMNS = ("country_name", "country_text_id", "year", "v2x_libdem")

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "political_freedom",
        "name": "Political freedom",
        "indicators": (
            {
                "key": "political_freedom",
                "code": "v2x_libdem",
                "name": "Political freedom",
                "unit": "0-100",
                "reversed_scale": False,
                "importance": 1.0,
                "summary": "V-Dem liberal democracy index, scaled from 0 to 100, combining free elections with civil liberties and the rule of law. The Varieties of Democracy project publishes the country-year scores under the CC BY-SA 4.0 license.",
            },
        ),
    },
)


class VdemImporter:
    """Download the V-Dem Country-Year Core file and store one JSON file per metric."""

    def __init__(
        self,
        start_year: int = DEFAULT_START_YEAR,
        end_year: int | None = None,
        output_dir: Path | None = None,
        include_series: bool = False,
        dataset_url: str = DATASET_URL,
    ) -> None:
        if end_year is None:
            end_year = datetime.now(timezone.utc).year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} is before start_year {start_year}")
        self.start_year = start_year
        self.end_year = end_year
        self.output_dir = output_dir or _repo_root() / "data"
        self.include_series = include_series
        self.dataset_url = dataset_url

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def fetch(self) -> pd.DataFrame:
        """Download the latest Country-Year Core zip and read the score columns."""
        _log(f"v-dem: downloading {self.dataset_url}")
        started = time.perf_counter()
        payload = _download(self.dataset_url)
        _log(f"v-dem: received {len(payload)} bytes in {_seconds(started)}")
        started = time.perf_counter()
        frame = _read_dataset(payload)
        _log(f"v-dem: read {len(frame)} country-years in {_seconds(started)}")
        return frame

    def to_documents(self, frame: pd.DataFrame | None = None) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric."""
        if frame is None:
            frame = self.fetch()
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        values = _scores(frame, self.start_year, self.end_year)
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                series = []
                for year in self.years:
                    data = [
                        {"country": name, "code": code, "value": value}
                        for code, (name, value) in sorted(
                            values.get(year, {}).items(),
                            key=lambda item: (item[1][0].casefold(), item[0]),
                        )
                    ]
                    series.append({"year": year, "count": len(data), "data": data})
                latest = _latest_country_rows(series)
                document = {
                    "metadata": {
                        "source": "Varieties of Democracy",
                        "scope": "World",
                        "database": "Country-Year Core v16",
                        "url": DATASET_PAGE,
                        "code": indicator["code"],
                        "key": indicator["key"],
                        "description": indicator["name"],
                        "summary": indicator["summary"],
                        "category": category["name"],
                        "units": indicator["unit"],
                        "reversedScale": indicator["reversed_scale"],
                        "importance": indicator["importance"],
                        "dataSize": len(latest),
                        "retrievedAt": retrieved_at,
                    },
                }
                if self.include_series:
                    document["series"] = series
                document["data"] = latest
                self._year_counts.append((indicator["key"], indicator["code"], series))
                documents.append((indicator["key"], document))
        return documents

    def save(self, documents: list[tuple[str, dict]]) -> list[Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for key, document in documents:
            path = self.output_dir / f"{key}.json"
            path.write_text(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            _log(f"v-dem saved {path.name} ({document['metadata']['dataSize']} countries)")
            paths.append(path)
        return paths

    def run(self) -> list[Path]:
        """Fetch the dataset and write one JSON file per metric into ``data/``."""
        _log(f"v-dem {self.start_year}-{self.end_year}: starting")
        documents = self.to_documents()
        paths = self.save(documents)
        _log_counts(self._year_counts)
        _log(f"v-dem done: {len(paths)} files in {self.output_dir}")
        return paths


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "data").is_dir() and (parent / "processes").is_dir():
            return parent
    raise FileNotFoundError(
        "Could not locate the repository root (expected data/ and processes/)."
    )


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def _read_dataset(payload: bytes) -> pd.DataFrame:
    """Read the country-year CSV from the V-Dem zip, keeping only the score columns."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected one CSV in the V-Dem archive, found {names}")
        _log(f"v-dem: reading {names[0]}")
        with archive.open(names[0]) as handle:
            return pd.read_csv(handle, usecols=list(SCORE_COLUMNS))


def _scores(
    frame: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[int, dict[str, tuple[str, float]]]:
    """Map year to ISO3 code to country name and a 0-100 score."""
    values: dict[int, dict[str, tuple[str, float]]] = {}
    for row in frame.to_dict(orient="records"):
        code = str(row.get("country_text_id") or "").strip().upper()
        name = str(row.get("country_name") or "").strip()
        year = _as_year(row.get("year"))
        score = _json_number(row.get("v2x_libdem"))
        if not ISO3.fullmatch(code) or not name or year is None or score is None:
            continue
        if year < start_year or year > end_year:
            continue
        values.setdefault(year, {})[code] = (name, round(score * 100, 4))
    return values


def _latest_country_rows(series: list[dict]) -> list[dict]:
    """Keep each country's value from the newest year in which it appears."""
    latest: dict[str, dict] = {}
    for entry in reversed(series):
        year = entry["year"]
        for row in entry["data"]:
            if row["code"] in latest:
                continue
            latest[row["code"]] = {
                "country": row["country"],
                "code": row["code"],
                "value": row["value"],
                "year": year,
            }
    return sorted(latest.values(), key=lambda row: (row["country"].casefold(), row["code"]))


def _log(message: str) -> None:
    print(message, flush=True)


def _seconds(started: float) -> str:
    return f"{time.perf_counter() - started:.1f}s"


def _log_counts(year_counts: list[tuple[str, str, list[dict]]]) -> None:
    for key, code, series in year_counts:
        _log(f"{key} ({code})")
        for entry in series:
            _log(f"  {entry['year']}: {entry['count']}")


def _as_year(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool) or pd.isna(value):
            return None
        year = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if 1900 <= year <= 2100:
        return year
    return None


def _json_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def main() -> None:
    VdemImporter().run()


if __name__ == "__main__":
    main()
