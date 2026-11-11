"""Import World Bank Open Data series into frontend JSON.

Fetches purchasing power, inflation, public health and education spending,
intentional homicides, and communications access for every World Bank
country. Each metric is written as its own JSON file, with metadata and the
latest value per country. Yearly series are omitted unless requested.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import wbgapi as wb

DEFAULT_START_YEAR = 2020

# Stable app keys sit next to the World Bank series codes. Names and units are
# the published WDI labels; keys stay fixed even if those labels change.
# reversed_scale is true when a higher value means worse conditions.
CATEGORIES = (
    {
        "id": "purchasing_power_and_inflation",
        "name": "Purchasing power parity and inflation",
        "indicators": (
            {
                "code": "NY.GDP.PCAP.PP.CD",
                "key": "gdp_per_capita_ppp",
                "name": "GDP per capita, PPP",
                "unit": "current international $",
                "reversed_scale": False,
                "summary": "Gross domestic product per person, converted to current international dollars so prices are comparable across countries. The World Bank compiles it from national accounts in the World Development Indicators.",
            },
            {
                "code": "FP.CPI.TOTL.ZG",
                "key": "inflation_rate",
                "name": "Inflation, consumer prices",
                "unit": "annual %",
                "reversed_scale": True,
                "summary": "Annual percentage change in consumer prices, showing how fast the cost of a typical household basket rises. National statistical offices report the index, and the World Bank republishes it.",
            },
        ),
    },
    {
        "id": "government_health_and_education",
        "name": "Government spending on health and education",
        "indicators": (
            {
                "code": "SH.XPD.GHED.GD.ZS",
                "key": "government_health_expenditure_gdp",
                "name": "Domestic general government health expenditure",
                "unit": "% of GDP",
                "reversed_scale": False,
                "summary": "Public spending on health by general government, measured as a share of gross domestic product. Figures come from the World Health Organization and are published in the World Bank indicators.",
            },
            {
                "code": "SE.XPD.TOTL.GD.ZS",
                "key": "government_education_expenditure_gdp",
                "name": "Government expenditure on education, total",
                "unit": "% of GDP",
                "reversed_scale": False,
                "summary": "All government spending on education, from primary school through higher education, as a share of gross domestic product. UNESCO collects the figures and the World Bank publishes them.",
            },
        ),
    },
    {
        "id": "crime",
        "name": "Crime rate",
        "indicators": (
            {
                "code": "VC.IHR.PSRC.P5",
                "key": "homicide_rate",
                "name": "Intentional homicides",
                "unit": "per 100,000 people",
                "reversed_scale": True,
                "summary": "Intentional killings recorded by police, counted per 100,000 people. The United Nations Office on Drugs and Crime compiles national justice statistics, and the World Bank publishes the series.",
            },
        ),
    },
    {
        "id": "communications_and_internet",
        "name": "Communications and internet access",
        "indicators": (
            {
                "code": "IT.NET.USER.ZS",
                "key": "internet_users",
                "name": "Individuals using the Internet",
                "unit": "% of population",
                "reversed_scale": False,
                "summary": "Share of people who used the internet during the past three months. National surveys and operator data are gathered by the International Telecommunication Union and published by the World Bank.",
            },
            {
                "code": "IT.NET.BBND.P2",
                "key": "fixed_broadband_subscriptions",
                "name": "Fixed broadband subscriptions",
                "unit": "per 100 people",
                "reversed_scale": False,
                "summary": "Fixed subscriptions that deliver broadband internet to homes and businesses, counted per 100 people. Telecom operators report the lines to the International Telecommunication Union, which the World Bank republishes.",
            },
            {
                "code": "IT.CEL.SETS.P2",
                "key": "mobile_subscriptions",
                "name": "Mobile cellular subscriptions",
                "unit": "per 100 people",
                "reversed_scale": False,
                "summary": "Active mobile-phone subscriptions, including prepaid accounts, counted per 100 people. A person may hold several lines. Operators report them to the International Telecommunication Union, and the World Bank publishes the series.",
            },
        ),
    },
)


class WorldBankImporter:
    """Download selected World Development Indicators and store one JSON file per metric."""

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

    def fetch(self) -> pd.DataFrame:
        """Return the wide World Bank frame for every configured series."""
        indicators = {
            indicator["code"]: indicator["key"]
            for category in CATEGORIES
            for indicator in category["indicators"]
        }
        return wb.data.DataFrame(
            indicators.keys(),
            economy="all",
            time=self.years,
            labels=True,
            numericTimeKeys=True,
            skipAggs=True,
        )

    def to_documents(self, frame: pd.DataFrame) -> list[tuple[str, dict]]:
        """Build one metadata-plus-series document per metric, for every requested year."""
        values, country_names, _series_names = _lookup(frame)
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                code = indicator["code"]
                series = []
                for year in self.years:
                    data = [
                        {
                            "country": country_names.get(country, country),
                            "code": country,
                            "value": values[(country, code, year)],
                        }
                        for country in _countries_with_value(values, country_names, code, year)
                    ]
                    series.append({"year": year, "count": len(data), "data": data})
                latest = _latest_country_rows(series)
                document = {
                    "metadata": {
                        "source": "World Bank Open Data",
                        "scope": "World",
                        "database": "World Development Indicators",
                        "url": "https://data.worldbank.org/",
                        "code": code,
                        "key": indicator["key"],
                        "description": indicator["name"],
                        "summary": indicator["summary"],
                        "category": category["name"],
                        "units": indicator["unit"],
                        "reversedScale": indicator["reversed_scale"],
                        "dataSize": len(latest),
                        "retrievedAt": retrieved_at,
                    },
                }
                if self.include_series:
                    document["series"] = series
                document["data"] = latest
                self._year_counts.append((indicator["key"], code, series))
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
        documents = self.to_documents(self.fetch())
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


def _lookup(
    frame: pd.DataFrame,
) -> tuple[dict[tuple[str, str, int], float | None], dict[str, str], dict[str, str]]:
    table = frame.reset_index()
    columns = list(table.columns)
    year_columns = {
        column: year
        for column in columns
        if (year := _as_year(column)) is not None
    }
    if "economy" not in columns or "series" not in columns:
        raise ValueError(f"Unexpected World Bank frame columns: {columns}")

    label_columns = [
        column
        for column in columns
        if column not in {"economy", "series"} and column not in year_columns
    ]
    values: dict[tuple[str, str, int], float | None] = {}
    country_names: dict[str, str] = {}
    series_names: dict[str, str] = {}
    for row in table.to_dict(orient="records"):
        country_code = str(row["economy"])
        indicator_code = str(row["series"])
        if label_columns:
            country_names[country_code] = str(row[label_columns[0]])
        if len(label_columns) > 1:
            series_names[indicator_code] = str(row[label_columns[1]])
        for column, year in year_columns.items():
            values[(country_code, indicator_code, year)] = _json_number(row[column])
    return values, country_names, series_names


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


def _countries_with_value(
    values: dict[tuple[str, str, int], float | None],
    country_names: dict[str, str],
    indicator_code: str,
    year: int,
) -> list[str]:
    countries = [
        country
        for (country, code, value_year), value in values.items()
        if code == indicator_code and value_year == year and value is not None
    ]
    return sorted(
        countries,
        key=lambda code: (country_names.get(code, code).casefold(), code),
    )


def _as_year(column: object) -> int | None:
    if isinstance(column, str):
        text = column[2:] if column.startswith("YR") else column
        if text.isdigit():
            year = int(text)
        else:
            return None
    else:
        try:
            if isinstance(column, bool):
                return None
            year = int(column)  # type: ignore[arg-type]
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
    WorldBankImporter().run()


if __name__ == "__main__":
    main()
