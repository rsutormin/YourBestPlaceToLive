"""Import Eurostat series into frontend JSON.

Loads house prices, rents, minimum and average hourly wages, first
residence and work permits, and transport volumes with ``eurostat.get_data_df``.
Each metric is written as its own JSON file under ``data/europe/`` in the same
shape as the other importers: metadata, an optional yearly ``series`` array,
and a ``data`` array of each country's latest value.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import eurostat
import pandas as pd

DEFAULT_START_YEAR = 2020

# Eurostat geo codes for countries. Aggregates such as EU and EA are omitted.
# EL is Greece and UK is the United Kingdom.
COUNTRIES = {
    "AL": ("ALB", "Albania"),
    "AT": ("AUT", "Austria"),
    "BA": ("BIH", "Bosnia and Herzegovina"),
    "BE": ("BEL", "Belgium"),
    "BG": ("BGR", "Bulgaria"),
    "CH": ("CHE", "Switzerland"),
    "CY": ("CYP", "Cyprus"),
    "CZ": ("CZE", "Czechia"),
    "DE": ("DEU", "Germany"),
    "DK": ("DNK", "Denmark"),
    "EE": ("EST", "Estonia"),
    "EL": ("GRC", "Greece"),
    "ES": ("ESP", "Spain"),
    "FI": ("FIN", "Finland"),
    "FR": ("FRA", "France"),
    "GE": ("GEO", "Georgia"),
    "HR": ("HRV", "Croatia"),
    "HU": ("HUN", "Hungary"),
    "IE": ("IRL", "Ireland"),
    "IS": ("ISL", "Iceland"),
    "IT": ("ITA", "Italy"),
    "LI": ("LIE", "Liechtenstein"),
    "LT": ("LTU", "Lithuania"),
    "LU": ("LUX", "Luxembourg"),
    "LV": ("LVA", "Latvia"),
    "MD": ("MDA", "Moldova"),
    "ME": ("MNE", "Montenegro"),
    "MK": ("MKD", "North Macedonia"),
    "MT": ("MLT", "Malta"),
    "NL": ("NLD", "Netherlands"),
    "NO": ("NOR", "Norway"),
    "PL": ("POL", "Poland"),
    "PT": ("PRT", "Portugal"),
    "RO": ("ROU", "Romania"),
    "RS": ("SRB", "Serbia"),
    "SE": ("SWE", "Sweden"),
    "SI": ("SVN", "Slovenia"),
    "SK": ("SVK", "Slovakia"),
    "TR": ("TUR", "Türkiye"),
    "UA": ("UKR", "Ukraine"),
    "UK": ("GBR", "United Kingdom"),
    "XK": ("XKX", "Kosovo"),
}

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "housing_costs",
        "name": "House prices and rents",
        "indicators": (
            {
                "key": "europe_house_price_index",
                "dataset": "prc_hpi_a",
                "code": "prc_hpi_a",
                "name": "House price index, annual average",
                "unit": "index, 2015=100",
                "reversed_scale": True,
                "importance": 0.5,
                "summary": "Annual index of dwelling prices paid by households, set to 100 in 2015. National statistical offices report transactions to Eurostat, which publishes one average for each calendar year.",
                "filters": {"freq": "A", "purchase": "TOTAL", "unit": "I15_A_AVG"},
            },
            {
                "key": "europe_rental_cost_index",
                "dataset": "prc_hicp_aind",
                "code": "prc_hicp_aind/CP041",
                "name": "Actual rentals for housing, HICP annual average index",
                "unit": "index",
                "reversed_scale": True,
                "importance": 0.5,
                "summary": "Annual index of rents households actually pay for their homes, from the harmonised consumer-price basket. National price collectors survey landlords and tenants, and Eurostat publishes the yearly average.",
                "filters": {"freq": "A", "unit": "INX_A_AVG", "coicop": "CP041"},
            },
        ),
    },
    {
        "id": "wages",
        "name": "Minimum and average wages",
        "indicators": (
            {
                "key": "europe_minimum_wage",
                "dataset": "earn_mw_cur",
                "code": "earn_mw_cur",
                "name": "Monthly minimum wage",
                "unit": "euro per month",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Statutory gross minimum wage for a full-time worker, converted to euros per month. National labour laws set the rate, and Eurostat records the latest figure published in each year.",
                "filters": {"freq": "S", "currency": "EUR"},
            },
            {
                "key": "europe_average_hourly_wage",
                "dataset": "lc_lci_lev",
                "code": "lc_lci_lev/B-N",
                "name": "Wages and salaries per hour, business economy, NACE B-N",
                "unit": "euro per hour",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Average wages and salaries paid per hour in the business economy, excluding agriculture and public administration. Employers report labour costs to national offices, and Eurostat publishes the annual level.",
                "filters": {
                    "freq": "A",
                    "unit": "EUR",
                    "lcstruct": "D11",
                    "nace_r2": "B-N",
                },
            },
        ),
    },
    {
        "id": "residence_permits",
        "name": "Residence and work permits",
        "indicators": (
            {
                "key": "europe_initial_residence_permits",
                "dataset": "migr_resfirst",
                "code": "migr_resfirst/TOTAL",
                "name": "First residence permits issued",
                "unit": "persons",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "First residence permits granted to non-EU citizens for any reason, not renewals. National immigration authorities issue them, and Eurostat totals the records reported by each country.",
                "filters": {
                    "freq": "A",
                    "reason": "TOTAL",
                    "citizen": "TOTAL",
                    "duration": "TOTAL",
                    "unit": "PER",
                },
            },
            {
                "key": "europe_work_permits",
                "dataset": "migr_resfirst",
                "code": "migr_resfirst/EMP",
                "name": "First residence permits issued for employment",
                "unit": "persons",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "First residence permits granted specifically so a non-EU citizen can take a job. National immigration authorities record the employment reason, and Eurostat totals those permits each year.",
                "filters": {
                    "freq": "A",
                    "reason": "EMP",
                    "citizen": "TOTAL",
                    "duration": "TOTAL",
                    "unit": "PER",
                },
            },
        ),
    },
    {
        "id": "transport",
        "name": "Transport connectivity and passenger traffic",
        "indicators": (
            {
                "key": "europe_motorway_length",
                "dataset": "road_if_motorwa",
                "code": "road_if_motorwa",
                "name": "Length of motorways",
                "unit": "kilometres",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Kilometres of motorway open to traffic. National road administrations measure the network once a year, and Eurostat publishes the reported length. It describes infrastructure, not how busy the roads are.",
                "filters": {"freq": "A", "tra_infr": "MWAY", "unit": "KM"},
            },
            {
                "key": "europe_railway_length",
                "dataset": "rail_if_line_tr",
                "code": "rail_if_line_tr",
                "name": "Length of railway lines",
                "unit": "kilometres",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Kilometres of railway line in operation, whatever the number of tracks. Infrastructure managers measure the network, and Eurostat publishes the annual length reported by each country.",
                "filters": {"freq": "A", "tra_infr": "TOTAL", "n_tracks": "TOTAL", "unit": "KM"},
            },
            {
                "key": "europe_air_passengers",
                "dataset": "avia_paoc",
                "code": "avia_paoc",
                "name": "Air passengers carried",
                "unit": "passengers",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Passengers carried on commercial flights, counting each boarding. A connecting trip can be counted more than once. Airports and airlines report the traffic, and Eurostat sums the annual total.",
                "filters": {
                    "freq": "A",
                    "unit": "PAS",
                    "tra_meas": "PAS_CRD",
                    "tra_cov": "TOTAL",
                    "schedule": "TOTAL",
                },
            },
            {
                "key": "europe_rail_passengers",
                "dataset": "rail_pa_total",
                "code": "rail_pa_total",
                "name": "Rail passengers",
                "unit": "thousand passengers",
                "reversed_scale": False,
                "importance": 0.5,
                "summary": "Journeys by rail passengers, published in thousands. One person making two trips counts twice. Railway operators report ticketed travel, and Eurostat compiles the annual total.",
                "filters": {"freq": "A", "unit": "THS_PAS"},
            },
        ),
    },
)


class EurostatImporter:
    """Download selected Eurostat datasets and store one JSON file per metric."""

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
        self.output_dir = output_dir or _repo_root() / "data" / "europe"
        self.include_series = include_series
        self._frames: dict[str, pd.DataFrame] = {}

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def fetch_frame(self, indicator: dict) -> pd.DataFrame:
        """Download one Eurostat dataset slice with ``get_data_df``."""
        cache_key = json.dumps(
            {"dataset": indicator["dataset"], "filters": indicator["filters"]},
            sort_keys=True,
        )
        if cache_key not in self._frames:
            frame = eurostat.get_data_df(
                indicator["dataset"],
                filter_pars=indicator["filters"],
            )
            if frame is None:
                raise ValueError(f"Eurostat returned no data for {indicator['dataset']}")
            self._frames[cache_key] = frame
        return self._frames[cache_key]

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
                        "source": "Eurostat",
                        "scope": "Europe",
                        "database": indicator["dataset"],
                        "url": "https://ec.europa.eu/eurostat",
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
        """Fetch the indicators and write one JSON file per metric into ``data/europe/``."""
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


def _values(
    frame: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[int, dict[str, tuple[str, float]]]:
    geo_column = next(column for column in frame.columns if str(column).startswith("geo"))
    columns_by_year: dict[int, list[object]] = {}
    for column in frame.columns:
        text = str(column)
        if len(text) >= 4 and text[:4].isdigit():
            columns_by_year.setdefault(int(text[:4]), []).append(column)

    values: dict[int, dict[str, tuple[str, float]]] = {}
    for row in frame.to_dict(orient="records"):
        country = COUNTRIES.get(str(row.get(geo_column)))
        if country is None:
            continue
        iso_code, country_name = country
        for year, columns in columns_by_year.items():
            if year < start_year or year > end_year:
                continue
            number = None
            for column in sorted(columns, key=str):
                parsed = _json_number(row.get(column))
                if parsed is not None:
                    number = parsed
            if number is None:
                continue
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
        if text in {"", ":"}:
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
    EurostatImporter().run()


if __name__ == "__main__":
    main()
