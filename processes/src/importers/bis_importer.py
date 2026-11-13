# Copyright (c) 2026 Roman Sutormin. MIT License.

"""Import BIS house-price series into frontend JSON.

Loads the selected residential property prices published by the Bank for
International Settlements with ``pandas.read_csv``. Each series is quarterly.
The JSON keeps one value per country and calendar year, taken from the latest
quarter of that year, in the same shape as the other importers.
"""

from __future__ import annotations

import io
import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_START_YEAR = 2020
DATASET_URL = "https://raw.githubusercontent.com/datasets/house-prices-global/master/data"
USER_AGENT = "YourBestPlaceToLive/0.1 (BIS data import)"

# BIS country codes are ISO 3166-1 alpha-2. Aggregates such as the euro area
# and the world total are omitted.
COUNTRIES = {
    "AT": ("AUT", "Austria"),
    "AU": ("AUS", "Australia"),
    "BE": ("BEL", "Belgium"),
    "BG": ("BGR", "Bulgaria"),
    "BR": ("BRA", "Brazil"),
    "CA": ("CAN", "Canada"),
    "CH": ("CHE", "Switzerland"),
    "CL": ("CHL", "Chile"),
    "CN": ("CHN", "China"),
    "CO": ("COL", "Colombia"),
    "CY": ("CYP", "Cyprus"),
    "CZ": ("CZE", "Czechia"),
    "DE": ("DEU", "Germany"),
    "DK": ("DNK", "Denmark"),
    "EE": ("EST", "Estonia"),
    "ES": ("ESP", "Spain"),
    "FI": ("FIN", "Finland"),
    "FR": ("FRA", "France"),
    "GB": ("GBR", "United Kingdom"),
    "GR": ("GRC", "Greece"),
    "HK": ("HKG", "Hong Kong"),
    "HR": ("HRV", "Croatia"),
    "HU": ("HUN", "Hungary"),
    "ID": ("IDN", "Indonesia"),
    "IE": ("IRL", "Ireland"),
    "IL": ("ISR", "Israel"),
    "IN": ("IND", "India"),
    "IS": ("ISL", "Iceland"),
    "IT": ("ITA", "Italy"),
    "JP": ("JPN", "Japan"),
    "KR": ("KOR", "Korea"),
    "LT": ("LTU", "Lithuania"),
    "LU": ("LUX", "Luxembourg"),
    "LV": ("LVA", "Latvia"),
    "MA": ("MAR", "Morocco"),
    "MK": ("MKD", "North Macedonia"),
    "MT": ("MLT", "Malta"),
    "MX": ("MEX", "Mexico"),
    "MY": ("MYS", "Malaysia"),
    "NL": ("NLD", "Netherlands"),
    "NO": ("NOR", "Norway"),
    "NZ": ("NZL", "New Zealand"),
    "PE": ("PER", "Peru"),
    "PH": ("PHL", "Philippines"),
    "PL": ("POL", "Poland"),
    "PT": ("PRT", "Portugal"),
    "RO": ("ROU", "Romania"),
    "RS": ("SRB", "Serbia"),
    "RU": ("RUS", "Russia"),
    "SE": ("SWE", "Sweden"),
    "SG": ("SGP", "Singapore"),
    "SI": ("SVN", "Slovenia"),
    "SK": ("SVK", "Slovakia"),
    "TH": ("THA", "Thailand"),
    "TR": ("TUR", "Türkiye"),
    "US": ("USA", "United States"),
    "ZA": ("ZAF", "South Africa"),
}

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "house_prices",
        "name": "House prices",
        "indicators": (
            {
                "key": "real_house_price_index",
                "file": "real_index.csv",
                "code": "real_index",
                "name": "Real house price index, latest quarter",
                "unit": "index, 2010=100",
                "reversed_scale": True,
                "importance": 0.75,
                "summary": "Inflation-adjusted index of residential property prices, set to 100 in 2010. National sources report quarterly prices to the Bank for International Settlements, and the latest quarter of each year is kept.",
            },
        ),
    },
)


class BisImporter:
    """Download BIS residential property prices and store one JSON file per metric."""

    def __init__(
        self,
        start_year: int = DEFAULT_START_YEAR,
        end_year: int | None = None,
        output_dir: Path | None = None,
        include_series: bool = False,
    ) -> None:
        if end_year is None:
            end_year = datetime.now(timezone.utc).year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} is before start_year {start_year}")
        self.start_year = start_year
        self.end_year = end_year
        self.output_dir = output_dir or _repo_root() / "data"
        self.include_series = include_series
        self._frames: dict[str, pd.DataFrame] = {}

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def fetch_frame(self, indicator: dict) -> pd.DataFrame:
        """Download one BIS CSV with ``pandas.read_csv``."""
        filename = indicator["file"]
        if filename not in self._frames:
            payload = _download(f"{DATASET_URL}/{filename}")
            frame = pd.read_csv(io.BytesIO(payload))
            if frame is None or frame.empty:
                raise ValueError(f"BIS returned no data for {filename}")
            self._frames[filename] = frame
        return self._frames[filename]

    def to_documents(self) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric."""
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                values = _values(self.fetch_frame(indicator), self.start_year, self.end_year)
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
                        "source": "Bank for International Settlements",
                        "scope": "World",
                        "database": indicator["file"],
                        "url": "https://www.bis.org/statistics/pp.htm",
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
            paths.append(path)
        return paths

    def run(self) -> list[Path]:
        """Fetch the indicators and write one JSON file per metric into ``data/``."""
        documents = self.to_documents()
        paths = self.save(documents)
        _log_counts(self._year_counts)
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
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _values(
    frame: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[int, dict[str, tuple[str, float]]]:
    values: dict[int, dict[str, tuple[str, float]]] = {}
    dated = frame.copy()
    dated["_date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated.dropna(subset=["_date"]).sort_values("_date")
    for row in dated.to_dict(orient="records"):
        country = COUNTRIES.get(str(row.get("country_code")))
        year = int(row["_date"].year)
        number = _json_number(row.get("price"))
        if country is None or number is None or year < start_year or year > end_year:
            continue
        iso_code, country_name = country
        values.setdefault(year, {})[iso_code] = (country_name, number)
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


def _log_counts(year_counts: list[tuple[str, str, list[dict]]]) -> None:
    for key, code, series in year_counts:
        print(f"{key} ({code})")
        for entry in series:
            print(f"  {entry['year']}: {entry['count']}")


def _json_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        value = text
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, 4)


def main() -> None:
    BisImporter().run()


if __name__ == "__main__":
    main()
