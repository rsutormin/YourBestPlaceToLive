# Copyright (c) 2026 Roman Sutormin. MIT License.

"""Import Our World in Data series into frontend JSON.

Loads air quality, CO2 emissions, life expectancy, infant mortality, education,
literacy, and Gallup life satisfaction with ``catalog.find``, then writes one
JSON file per metric. The document matches the World Bank importer: metadata,
an optional yearly ``series`` array, and a ``data`` array of each country's
latest value.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from owid import catalog

DEFAULT_START_YEAR = 2020
ISO3 = re.compile(r"^[A-Z]{3}$")

# Stable app keys sit next to the OWID column names. Names and units are the
# published labels; keys stay fixed even if those labels change.
# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "air_quality_and_emissions",
        "name": "Air quality and emissions",
        "indicators": (
            {
                "key": "pm25_exposure",
                "column": "population_weighted_pm25",
                "name": "Outdoor air pollution exposure, population-weighted PM2.5",
                "unit": "µg/m³",
                "reversed_scale": True,
                "importance": 1.0,
                "summary": "Average outdoor exposure to fine particulate matter, weighted by where people live. Satellite and ground measurements are modelled by Washington University and compiled by Our World in Data.",
                "table": "pm25_air_pollution",
                "dataset": "pm25_air_pollution",
                "namespace": "washu",
            },
            {
                "key": "co2_emissions_per_capita",
                "column": "co2_per_capita",
                "name": "Annual CO₂ emissions, per capita",
                "unit": "tonnes per person",
                "reversed_scale": True,
                "importance": 0.25,
                "summary": "Carbon dioxide released each year from fossil fuels and industry, divided by population. The Global Carbon Project assembles national energy and cement statistics, and Our World in Data republishes them.",
                "table": "owid_co2",
                "dataset": "owid_co2",
                "namespace": "emissions",
                "code_column": "iso_code",
            },
        ),
    },
    {
        "id": "life_expectancy_and_infant_mortality",
        "name": "Life expectancy and infant mortality",
        "indicators": (
            {
                "key": "life_expectancy",
                "column": "life_expectancy_0",
                "name": "Period life expectancy at birth",
                "unit": "years",
                "reversed_scale": False,
                "importance": 0.75,
                "summary": "Average years a newborn would live if current death rates stayed unchanged. The United Nations population estimates calculate it from registered deaths and censuses, and Our World in Data republishes the series.",
                "table": "life_expectancy_at_birth",
                "dataset": "life_expectancy",
                "namespace": "demography",
            },
            {
                "key": "infant_mortality_rate",
                "column": "mortality_rate",
                "name": "Infant mortality rate",
                "unit": "% of infants",
                "reversed_scale": True,
                "importance": 1.0,
                "summary": "Share of infants who die before their first birthday. The United Nations World Population Prospects estimates it from vital registration and surveys, and Our World in Data republishes the rate.",
                "table": "mortality_rate",
                "dataset": "un_wpp",
                "namespace": "un",
                "filters": {"sex": "all", "age": "0", "variant": "estimates"},
            },
        ),
    },
    {
        "id": "education_and_literacy",
        "name": "Education and literacy",
        "indicators": (
            {
                "key": "mean_years_of_schooling",
                "column": "mean_years_of_schooling__isced_1_or_higher__population_25plus_years__both_sexes",
                "name": "Average years of schooling",
                "unit": "years",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Average years of formal schooling completed by adults aged 25 and older. UNESCO compiles school enrolment and attainment records, and Our World in Data republishes the national averages.",
                "table": "education_opri",
                "dataset": "education_opri",
                "namespace": "unesco",
            },
            {
                "key": "adult_literacy_rate",
                "column": "adult_literacy_rate__population_15plus_years__both_sexes__pct__lr_ag15t99",
                "name": "Literacy rate among adults",
                "unit": "%",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Share of people aged 15 and older who can read and write a short statement about everyday life. UNESCO gathers literacy surveys and censuses, and Our World in Data republishes the rate.",
                "table": "education_sdgs",
                "dataset": "education_sdgs",
                "namespace": "unesco",
            },
        ),
    },
    {
        "id": "happiness_and_life_satisfaction",
        "name": "Happiness and life satisfaction",
        "indicators": (
            {
                "key": "life_satisfaction",
                "column": "cantril_ladder_score",
                "name": "Life satisfaction, Cantril ladder, Gallup World Poll",
                "unit": "0-10",
                "reversed_scale": False,
                "importance": 1.0,
                "summary": "How people rate their life today, on a ladder from 0 to 10. Gallup asks this in its World Poll, and Our World in Data republishes the national average score.",
                "table": "happiness",
                "dataset": "happiness",
                "namespace": "happiness",
            },
        ),
    },
)


class OwidImporter:
    """Download selected Our World in Data tables and store one JSON file per metric."""

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

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def fetch_table(self, indicator: dict) -> pd.DataFrame:
        """Load the latest catalog table for one indicator."""
        matches = catalog.find(
            indicator["table"],
            namespace=indicator["namespace"],
            dataset=indicator["dataset"],
        )
        if matches.empty:
            raise ValueError(
                f"No OWID table found for {indicator['namespace']}/"
                f"{indicator['dataset']}/{indicator['table']}"
            )
        if (matches.version == "latest").any():
            row = matches[matches.version == "latest"].iloc[-1]
        else:
            row = matches.sort_values("version").iloc[-1]
        frame = row.load().reset_index()
        filters = indicator.get("filters") or {}
        for column, expected in filters.items():
            frame = frame[frame[column].astype(str) == expected]
        return frame

    def to_documents(self) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric."""
        country_codes = _country_codes()
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                frame = self.fetch_table(indicator)
                values = _values(frame, indicator, country_codes)
                series = []
                for year in self.years:
                    data = [
                        {
                            "country": country_name,
                            "code": code,
                            "value": value,
                        }
                        for code, (country_name, value) in sorted(
                            values.get(year, {}).items(),
                            key=lambda item: (item[1][0].casefold(), item[0]),
                        )
                    ]
                    series.append({"year": year, "count": len(data), "data": data})
                latest = _latest_country_rows(series)
                document = {
                    "metadata": {
                        "source": "Our World in Data",
                        "scope": "World",
                        "database": indicator["dataset"],
                        "url": "https://ourworldindata.org/",
                        "code": indicator["column"],
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
                self._year_counts.append((indicator["key"], indicator["column"], series))
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


def _country_codes() -> dict[str, str]:
    """Map OWID country names to ISO alpha-3 codes, skipping regions."""
    matches = catalog.find("regions", namespace="regions", dataset="regions")
    if matches.empty:
        raise ValueError("No OWID regions table found")
    regions = matches.sort_values("version").iloc[-1].load()
    current = regions[
        (regions["region_type"] == "country")
        & (~regions["is_historical"].fillna(False).astype(bool))
    ]
    codes: dict[str, str] = {}
    for iso_code, row in current.iterrows():
        iso = str(row["iso_alpha3"] or iso_code)
        if not ISO3.fullmatch(iso):
            continue
        for label in (row["name"], row["short_name"]):
            _add_code(codes, label, iso)
    for iso_code, row in current.iterrows():
        iso = str(row["iso_alpha3"] or iso_code)
        if not ISO3.fullmatch(iso):
            continue
        for label in _alias_labels(row["aliases"]):
            _add_code(codes, label, iso)
    return codes


def _add_code(codes: dict[str, str], label: object, iso: str) -> None:
    if label is None or pd.isna(label):
        return
    name = str(label).strip()
    if name and name not in codes:
        codes[name] = iso


def _alias_labels(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return [text] if text else []


def _values(
    frame: pd.DataFrame,
    indicator: dict,
    country_codes: dict[str, str],
) -> dict[int, dict[str, tuple[str, float]]]:
    column = indicator["column"]
    code_column = indicator.get("code_column")
    values: dict[int, dict[str, tuple[str, float]]] = {}
    for row in frame.to_dict(orient="records"):
        number = _json_number(row.get(column))
        if number is None:
            continue
        year = _as_year(row.get("year"))
        if year is None:
            continue
        country_name = str(row.get("country") or "").strip()
        if code_column:
            code = row.get(code_column)
            iso = str(code).strip() if code is not None and not pd.isna(code) else ""
        else:
            iso = country_codes.get(country_name, "")
        if not ISO3.fullmatch(iso):
            continue
        values.setdefault(year, {}).setdefault(iso, (country_name, number))
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


def _as_year(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        if isinstance(value, bool):
            return None
        year = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if 1900 <= year <= 2100:
        return year
    return None


def _json_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)  # type: ignore[arg-type]
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, 4)


def main() -> None:
    OwidImporter().run()


if __name__ == "__main__":
    main()
