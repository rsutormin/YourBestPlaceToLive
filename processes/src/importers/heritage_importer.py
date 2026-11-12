"""Import Heritage Foundation Index of Economic Freedom scores.

Each edition is an Excel workbook at a stable public URL. The sheet layout
changes between editions: some include a year column, and some component
headings are misspelled. Columns are chosen by their labels. A missing
workbook is skipped so an unpublished year does not stop the import.
"""

from __future__ import annotations

import io
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_START_YEAR = 2020
FILE_URL = "https://static.heritage.org/index/data/{year}/{year}_indexofeconomicfreedom_data.xlsx"
DATASET_PAGE = "https://www.heritage.org/index/"
USER_AGENT = "YourBestPlaceToLive/0.1 (Heritage Index of Economic Freedom import)"
ISO3 = re.compile(r"^[A-Z]{3}$")

# Heritage names that do not match the map files.
ALIASES = {
    "Bosnia and Herzegovina": "BIH",
    "Brunei Darussalam": "BRN",
    "Burma": "MMR",
    "Central African Republic": "CAF",
    "Czech Republic": "CZE",
    "Democratic Republic of Congo": "COD",
    "Dominican Republic": "DOM",
    "Equatorial Guinea": "GNQ",
    "Eswatini": "SWZ",
    "Kyrgyz Republic": "KGZ",
    "Micronesia": "FSM",
    "Republic of Congo": "COG",
    "Saint Lucia": "LCA",
    "Saint Vincent and The Grenadines": "VCT",
    "Saint Vincent and the Grenadines": "VCT",
    "Solomon Islands": "SLB",
    "São Tomé and Príncipe": "STP",
    "Sao Tome and Principe": "STP",
    "The Bahamas": "BHS",
    "The Gambia": "GMB",
    "The Philippines": "PHL",
    "Türkiye": "TUR",
    "United States": "USA",
}

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "economic_freedom",
        "name": "Economic freedom",
        "indicators": (
            {
                "key": "economic_freedom",
                "code": "overall_score",
                "field": "overall",
                "name": "Economic freedom score",
                "unit": "0-100",
                "reversed_scale": False,
                "importance": 0.75,
                "summary": "Heritage Foundation Index of Economic Freedom overall score, from 0 to 100, averaging property rights, tax burden, government size, and open markets. Higher scores mean fewer policy barriers to work, investment, and trade.",
            },
            {
                "key": "business_freedom",
                "code": "hf_business",
                "field": "business",
                "name": "Business freedom",
                "unit": "0-100",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Ease of opening, running, and closing a company, scored from 0 to 100 in the Heritage Foundation Index of Economic Freedom. The business freedom component uses regulatory quality, infrastructure, and inclusion measures.",
            },
        ),
    },
)


class HeritageImporter:
    """Download Index of Economic Freedom workbooks and store one JSON file per metric."""

    def __init__(
        self,
        start_year: int = DEFAULT_START_YEAR,
        end_year: int | None = None,
        output_dir: Path | None = None,
        include_series: bool = False,
        file_url: str = FILE_URL,
    ) -> None:
        if end_year is None:
            end_year = datetime.now(timezone.utc).year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} is before start_year {start_year}")
        self.start_year = start_year
        self.end_year = end_year
        self.output_dir = output_dir or _repo_root() / "data"
        self.include_series = include_series
        self.file_url = file_url

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def fetch(self) -> dict[int, pd.DataFrame]:
        """Download each published workbook. A 404 means that edition is not posted yet."""
        frames = {}
        for year in self.years:
            url = self.file_url.format(year=year)
            _log(f"heritage: downloading {url}")
            started = time.perf_counter()
            try:
                payload = _download(url)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    _log(f"heritage: {year} workbook is not published")
                    continue
                raise
            _log(f"heritage: received {len(payload)} bytes in {_seconds(started)}")
            frames[year] = pd.read_excel(io.BytesIO(payload), header=None)
        if not frames:
            raise ValueError(
                "Heritage published no Index of Economic Freedom workbooks "
                f"for {self.start_year}-{self.end_year}"
            )
        return frames

    def to_documents(
        self,
        frames: dict[int, pd.DataFrame] | None = None,
    ) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric."""
        if frames is None:
            frames = self.fetch()
        if not frames:
            raise ValueError(
                "Heritage published no Index of Economic Freedom workbooks "
                f"for {self.start_year}-{self.end_year}"
            )
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        codes = _country_codes()
        rows = []
        unmapped: set[str] = set()
        for year in sorted(frames):
            year_rows, missing = _score_rows(frames[year], year, codes)
            rows.extend(year_rows)
            unmapped.update(missing)
        if unmapped:
            _log(f"heritage: skipped unmapped countries {', '.join(sorted(unmapped))}")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                series = _series(rows, indicator["field"])
                latest = _latest_country_rows(series)
                document = {
                    "metadata": {
                        "source": "Heritage Foundation",
                        "scope": "World",
                        "database": "Index of Economic Freedom",
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
            _log(f"heritage saved {path.name} ({document['metadata']['dataSize']} countries)")
            paths.append(path)
        return paths

    def run(self) -> list[Path]:
        """Fetch the workbooks and write one JSON file per metric into ``data/``."""
        _log(f"heritage {self.start_year}-{self.end_year}: starting")
        documents = self.to_documents()
        paths = self.save(documents)
        _log_counts(self._year_counts)
        _log(f"heritage done: {len(paths)} files in {self.output_dir}")
        return paths


def _score_rows(
    frame: pd.DataFrame,
    edition_year: int,
    codes: dict[str, str],
) -> tuple[list[dict], list[str]]:
    """Read one workbook sheet into country rows for both scores."""
    header_index, columns = _columns(frame)
    country_at, overall_at, business_at, year_at = columns
    rows = []
    unmapped = []
    seen: set[str] = set()
    for _, record in frame.iloc[header_index + 1 :].iterrows():
        values = record.tolist()
        name = _country_name(values[country_at] if country_at < len(values) else None)
        if not name:
            continue
        code = _lookup(name, codes)
        if code is None:
            unmapped.append(name)
            continue
        if code in seen:
            continue
        seen.add(code)
        year = edition_year
        if year_at is not None and year_at < len(values):
            parsed = _as_year(values[year_at])
            if parsed is not None:
                year = parsed
        rows.append(
            {
                "country": name,
                "code": code,
                "year": year,
                "overall": _score(values[overall_at] if overall_at < len(values) else None),
                "business": _score(values[business_at] if business_at < len(values) else None),
            }
        )
    return rows, unmapped


def _columns(frame: pd.DataFrame) -> tuple[int, tuple[int, int, int, int | None]]:
    """Locate the header row and the country, overall, business, and year columns."""
    for index, record in frame.iterrows():
        labels = [_label(value) for value in record.tolist()]
        if "country" not in labels:
            continue
        overall = _column_index(labels, lambda label: "overall" in label and "score" in label)
        business = _column_index(labels, lambda label: "business" in label and "freedom" in label)
        if overall is None or business is None:
            continue
        year = _column_index(labels, lambda label: label == "year")
        return int(index), (labels.index("country"), overall, business, year)
    raise ValueError("Heritage workbook has no overall score or business freedom column")


def _column_index(labels: list[str], matches) -> int | None:
    for index, label in enumerate(labels):
        if matches(label):
            return index
    return None


def _series(rows: list[dict], field: str) -> list[dict]:
    by_year: dict[int, dict[str, dict]] = {}
    for row in rows:
        value = row[field]
        if value is None:
            continue
        by_year.setdefault(row["year"], {})[row["code"]] = {
            "country": row["country"],
            "code": row["code"],
            "value": value,
        }
    series = []
    for year in sorted(by_year):
        data = sorted(by_year[year].values(), key=lambda item: (item["country"].casefold(), item["code"]))
        series.append({"year": year, "count": len(data), "data": data})
    return series


def _lookup(name: str, codes: dict[str, str]) -> str | None:
    if name in codes:
        return codes[name]
    normalized = _normalize_name(name)
    if normalized in codes:
        return codes[normalized]
    return ALIASES.get(name) or ALIASES.get(normalized)


def _normalize_name(name: str) -> str:
    return name.replace("’", "'").replace("‘", "'")


def _country_name(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _country_codes() -> dict[str, str]:
    """Map display names, including Heritage aliases, to ISO alpha-3 codes."""
    codes: dict[str, str] = {}
    root = _repo_root()
    for relative in ("frontend/src/world-countries.json", "frontend/src/country-points.json"):
        data = json.loads((root / relative).read_text(encoding="utf-8"))
        features = data["features"] if isinstance(data, dict) and "features" in data else data
        for feature in features:
            props = feature.get("properties", feature)
            iso = str(props.get("iso_a3") or "").upper()
            name = str(props.get("name") or "").strip()
            if name and ISO3.fullmatch(iso) and name not in codes:
                codes[name] = iso
    codes.update(ALIASES)
    return codes


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "data").is_dir() and (parent / "processes").is_dir():
            return parent
    raise FileNotFoundError(
        "Could not locate the repository root (expected data/ and processes/)."
    )


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


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


def _label(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).casefold()


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


def _score(value: object) -> float | None:
    number = _json_number(value)
    if number is None or number < 0 or number > 100:
        return None
    return round(number, 4)


def _json_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text.casefold() in {"", "n/a", "na", "-", "—"}:
            return None
        value = text
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
    HeritageImporter().run()


if __name__ == "__main__":
    main()
