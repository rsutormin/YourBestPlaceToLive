"""Import OECD series into frontend JSON.

Loads the tax wedge, employees working very long hours, and household income
per capita from the OECD Data Explorer SDMX API with ``pandas.read_csv``.
PISA mean scores are not published in that catalogue, so they are read from
the official PISA results annex. Each metric is written as its own JSON file
in the same shape as the other importers.
"""

from __future__ import annotations

import io
import json
import math
import re
import urllib.request
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_START_YEAR = 2020
SDMX_URL = "https://sdmx.oecd.org/public/rest/data"
PISA_ANNEX_URL = "https://stat.link/mrq53f"
USER_AGENT = "YourBestPlaceToLive/0.1 (OECD data import)"

# Reference-area codes that are groups rather than countries.
AGGREGATES = {
    "E",
    "EA",
    "EA19",
    "EA20",
    "EA21",
    "EU",
    "EU15",
    "EU19OECD",
    "EU22OECD",
    "EU27",
    "EU27_2020",
    "EU28",
    "G20",
    "G7",
    "O",
    "OAVG",
    "OECD",
    "OECD_REP",
    "WLD",
}

# PISA prints country and economy names. Sub-national samples are left out.
PISA_COUNTRIES = {
    "Albania": ("ALB", "Albania"),
    "Argentina": ("ARG", "Argentina"),
    "Armenia": ("ARM", "Armenia"),
    "Australia": ("AUS", "Australia"),
    "Austria": ("AUT", "Austria"),
    "Azerbaijan": ("AZE", "Azerbaijan"),
    "Belgium": ("BEL", "Belgium"),
    "Brazil": ("BRA", "Brazil"),
    "Brunei Darussalam": ("BRN", "Brunei Darussalam"),
    "Bulgaria": ("BGR", "Bulgaria"),
    "Cambodia": ("KHM", "Cambodia"),
    "Canada": ("CAN", "Canada"),
    "Chile": ("CHL", "Chile"),
    "Chinese Taipei": ("TWN", "Taiwan"),
    "Colombia": ("COL", "Colombia"),
    "Costa Rica": ("CRI", "Costa Rica"),
    "Croatia": ("HRV", "Croatia"),
    "Cyprus": ("CYP", "Cyprus"),
    "Czechia": ("CZE", "Czechia"),
    "Denmark": ("DNK", "Denmark"),
    "Dominican Republic": ("DOM", "Dominican Republic"),
    "Ecuador": ("ECU", "Ecuador"),
    "El Salvador": ("SLV", "El Salvador"),
    "Estonia": ("EST", "Estonia"),
    "Finland": ("FIN", "Finland"),
    "France": ("FRA", "France"),
    "Georgia": ("GEO", "Georgia"),
    "Germany": ("DEU", "Germany"),
    "Greece": ("GRC", "Greece"),
    "Guatemala": ("GTM", "Guatemala"),
    "Hong Kong (China)": ("HKG", "Hong Kong"),
    "Hungary": ("HUN", "Hungary"),
    "Iceland": ("ISL", "Iceland"),
    "Indonesia": ("IDN", "Indonesia"),
    "Ireland": ("IRL", "Ireland"),
    "Israel": ("ISR", "Israel"),
    "Italy": ("ITA", "Italy"),
    "Japan": ("JPN", "Japan"),
    "Jordan": ("JOR", "Jordan"),
    "Kazakhstan": ("KAZ", "Kazakhstan"),
    "Kenya": ("KEN", "Kenya"),
    "Korea": ("KOR", "Korea"),
    "Kosovo": ("XKX", "Kosovo"),
    "Kyrgyzstan": ("KGZ", "Kyrgyzstan"),
    "Latvia": ("LVA", "Latvia"),
    "Lebanon": ("LBN", "Lebanon"),
    "Lithuania": ("LTU", "Lithuania"),
    "Luxembourg": ("LUX", "Luxembourg"),
    "Macao (China)": ("MAC", "Macao"),
    "Malaysia": ("MYS", "Malaysia"),
    "Malta": ("MLT", "Malta"),
    "Mauritius": ("MUS", "Mauritius"),
    "Mexico": ("MEX", "Mexico"),
    "Moldova": ("MDA", "Moldova"),
    "Mongolia": ("MNG", "Mongolia"),
    "Montenegro": ("MNE", "Montenegro"),
    "Morocco": ("MAR", "Morocco"),
    "Netherlands": ("NLD", "Netherlands"),
    "New Zealand": ("NZL", "New Zealand"),
    "North Macedonia": ("MKD", "North Macedonia"),
    "Norway": ("NOR", "Norway"),
    "Palestinian Authority": ("PSE", "Palestine"),
    "Paraguay": ("PRY", "Paraguay"),
    "Peru": ("PER", "Peru"),
    "Philippines": ("PHL", "Philippines"),
    "Poland": ("POL", "Poland"),
    "Portugal": ("PRT", "Portugal"),
    "Qatar": ("QAT", "Qatar"),
    "Romania": ("ROU", "Romania"),
    "Rwanda": ("RWA", "Rwanda"),
    "Saudi Arabia": ("SAU", "Saudi Arabia"),
    "Serbia": ("SRB", "Serbia"),
    "Singapore": ("SGP", "Singapore"),
    "Slovak Republic": ("SVK", "Slovakia"),
    "Slovenia": ("SVN", "Slovenia"),
    "Spain": ("ESP", "Spain"),
    "Sweden": ("SWE", "Sweden"),
    "Switzerland": ("CHE", "Switzerland"),
    "Thailand": ("THA", "Thailand"),
    "Türkiye": ("TUR", "Türkiye"),
    "United Arab Emirates": ("ARE", "United Arab Emirates"),
    "United Kingdom": ("GBR", "United Kingdom"),
    "United States": ("USA", "United States"),
    "Uruguay": ("URY", "Uruguay"),
    "Uzbekistan": ("UZB", "Uzbekistan"),
    "Viet Nam": ("VNM", "Viet Nam"),
    "Zambia": ("ZMB", "Zambia"),
}

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "tax_burden",
        "name": "Tax burden on wages",
        "indicators": (
            {
                "key": "tax_wedge",
                "dataset": "DSD_TAX_WAGES_COMP@DF_TW_COMP",
                "code": "AV_TW/S_C0/AW100",
                "name": "Average tax wedge, single person at the average wage",
                "unit": "percentage of labour costs",
                "reversed_scale": True,
                "importance": 0.75,
                "summary": "Income tax plus employee and employer social contributions for a childless single person earning the average wage, as a share of labour costs. The OECD calculates this in Taxing Wages.",
                "url": "https://data-explorer.oecd.org/",
                "source_url": (
                    f"{SDMX_URL}/OECD.CTP.TPS,DSD_TAX_WAGES_COMP@DF_TW_COMP/"
                    ".AV_TW.PT_COS_LB.S_C0.AW100._Z.A"
                ),
            },
        ),
    },
    {
        "id": "work_life_balance",
        "name": "Work-life balance",
        "indicators": (
            {
                "key": "overtime_workers",
                "dataset": "DSD_HW@DF_LNG_WK_HRS",
                "code": "EMP/H_GE50/ICSE93_1",
                "name": "Employees usually working 50 or more hours per week",
                "unit": "thousand persons",
                "reversed_scale": True,
                "importance": 0.5,
                "url": "https://data-explorer.oecd.org/",
                "source_url": (
                    f"{SDMX_URL}/OECD.ELS.SAE,DSD_HW@DF_LNG_WK_HRS/"
                    ".EMP.PS._T._T.EMP.W.USUAL.ICSE93_1._Z.OBS.H_GE50.MAIN"
                ),
                "export": False,
            },
            {
                "key": "overtime_workers_percentage",
                "dataset": "DSD_HW@DF_LNG_WK_HRS / DSD_LFS@DF_LFS",
                "code": "EMP/H_GE50/ICSE93_1 / POP/PS/EMP",
                "name": "Employees usually working 50 or more hours per week, percentage of total employment",
                "unit": "percent",
                "reversed_scale": True,
                "importance": 0.5,
                "url": "https://data-explorer.oecd.org/",
                "numerator": "overtime_workers",
                "denominator": "total_workers",
                "summary": "Employees who usually work 50 hours or more a week on their main job, as a percentage of everyone in employment that year. The OECD labour-force statistics supply both counts.",
            },
        ),
    },
    {
        "id": "employment",
        "name": "Employment",
        "indicators": (
            {
                "key": "total_workers",
                "dataset": "DSD_LFS@DF_LFS",
                "code": "POP/PS/EMP",
                "name": "Total employment",
                "unit": "thousand persons",
                "reversed_scale": False,
                "importance": 0.5,
                "url": "https://data-explorer.oecd.org/",
                "source_url": f"{SDMX_URL}/OECD.ELS.SAE,DSD_LFS@DF_LFS/.POP.PS._T._T.EMP",
                "export": False,
            },
        ),
    },
    {
        "id": "income",
        "name": "Average annual income",
        "indicators": (
            {
                "key": "average_annual_income_per_capita",
                "dataset": "DSD_NAAG@DF_NAAG_V",
                "code": "B7GS1M_POP/USD_PPP_PS",
                "name": "Gross adjusted disposable income per capita, PPP converted",
                "unit": "US dollars per person",
                "reversed_scale": False,
                "importance": 0.75,
                "summary": "Household income left after taxes and transfers, plus the value of public services, per person in comparable US dollars. The OECD calculates it from each country's national accounts.",
                "url": "https://data-explorer.oecd.org/",
                "source_url": (
                    f"{SDMX_URL}/OECD.SDD.NAD,DSD_NAAG@DF_NAAG_V/"
                    "A..B7GS1M_POP.USD_PPP_PS.NAAG_V"
                ),
            },
        ),
    },
    {
        "id": "school_results",
        "name": "School education results",
        "indicators": (
            {
                "key": "pisa_mathematics",
                "dataset": "PISA Table I.B1.2a.38",
                "code": "PISA/mathematics",
                "name": "PISA mean score in mathematics",
                "unit": "mean score",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Average mathematics score of 15-year-old students on the OECD PISA test. Schools are sampled to represent each country, and the comparable trend figures come from the PISA 2025 results annex.",
                "url": "https://www.oecd.org/en/about/programmes/pisa/",
                "sheet": "Table I.B1.2a.38",
            },
            {
                "key": "pisa_reading",
                "dataset": "PISA Table I.B1.2a.37",
                "code": "PISA/reading",
                "name": "PISA mean score in reading",
                "unit": "mean score",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Average reading score of 15-year-old students on the OECD PISA test. Schools are sampled to represent each country, and the comparable trend figures come from the PISA 2025 results annex.",
                "url": "https://www.oecd.org/en/about/programmes/pisa/",
                "sheet": "Table I.B1.2a.37",
            },
            {
                "key": "pisa_science",
                "dataset": "PISA Table I.B1.2a.36",
                "code": "PISA/science",
                "name": "PISA mean score in science",
                "unit": "mean score",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Average science score of 15-year-old students on the OECD PISA test. Schools are sampled to represent each country, and the comparable trend figures come from the PISA 2025 results annex.",
                "url": "https://www.oecd.org/en/about/programmes/pisa/",
                "sheet": "Table I.B1.2a.36",
            },
        ),
    },
)


class OecdImporter:
    """Download selected OECD datasets and store one JSON file per metric."""

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
        self._pisa_workbook: pd.ExcelFile | None = None

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def fetch_frame(self, indicator: dict) -> pd.DataFrame:
        """Download one OECD table as a DataFrame."""
        if "sheet" in indicator:
            return self._pisa_sheet(indicator["sheet"])
        if indicator["source_url"] not in self._frames:
            query = (
                f"{indicator['source_url']}"
                f"?startPeriod={self.start_year}"
                "&dimensionAtObservation=AllDimensions"
                "&format=csvfilewithlabels"
            )
            self._frames[indicator["source_url"]] = _read_csv(_download(query))
        return self._frames[indicator["source_url"]]

    def _percentage_values(
        self,
        numerator_key: str,
        denominator_key: str,
    ) -> dict[int, dict[str, tuple[str, float]]]:
        """Percentage of the numerator in the denominator, for each country and year both exist."""
        numerator = _values(
            self.fetch_frame(_indicator(numerator_key)),
            self.start_year,
            self.end_year,
        )
        denominator = _values(
            self.fetch_frame(_indicator(denominator_key)),
            self.start_year,
            self.end_year,
        )
        values: dict[int, dict[str, tuple[str, float]]] = {}
        for year, rows in numerator.items():
            bases = denominator.get(year, {})
            for code, (name, count) in rows.items():
                base = bases.get(code)
                if base is None or base[1] <= 0:
                    continue
                values.setdefault(year, {})[code] = (name, round(count / base[1] * 100, 4))
        return values

    def to_documents(self, keys: Collection[str] | None = None) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric."""
        selected = None if keys is None else set(keys)
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                if selected is not None and indicator["key"] not in selected:
                    continue
                if not indicator.get("export", True):
                    continue
                if "numerator" in indicator:
                    values = self._percentage_values(indicator["numerator"], indicator["denominator"])
                else:
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
                        "source": "OECD",
                        "scope": "World",
                        "database": indicator["dataset"],
                        "url": indicator["url"],
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

    def run(self, keys: Collection[str] | None = None) -> list[Path]:
        """Fetch the indicators and write one JSON file per metric into ``data/``."""
        documents = self.to_documents(keys)
        paths = self.save(documents)
        _log_counts(self._year_counts)
        return paths

    def _pisa_sheet(self, sheet: str) -> pd.DataFrame:
        if self._pisa_workbook is None:
            self._pisa_workbook = pd.ExcelFile(io.BytesIO(_download(PISA_ANNEX_URL)))
        frame = self._pisa_workbook.parse(sheet, header=None)
        return _pisa_frame(frame)


def _indicator(key: str) -> dict:
    for category in CATEGORIES:
        for indicator in category["indicators"]:
            if indicator["key"] == key:
                return indicator
    raise KeyError(key)


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


def _read_csv(payload: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(payload))
    if frame is None or frame.empty:
        raise ValueError("OECD returned no rows")
    return frame


def _values(
    frame: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> dict[int, dict[str, tuple[str, float]]]:
    values: dict[int, dict[str, tuple[str, float]]] = {}
    for row in frame.to_dict(orient="records"):
        code = str(row.get("REF_AREA") or "")
        if not re.fullmatch(r"[A-Z]{3}", code) or code in AGGREGATES:
            continue
        year = _year(row.get("TIME_PERIOD"))
        number = _json_number(row.get("OBS_VALUE"))
        if year is None or number is None or year < start_year or year > end_year:
            continue
        country = str(row.get("country") or row.get("Reference area") or code).strip()
        values.setdefault(year, {})[code] = (country, number)
    return values


def _pisa_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn a PISA mean-score sheet into REF_AREA, country, TIME_PERIOD, OBS_VALUE."""
    header_row = next(
        index
        for index, value in frame.iloc[:, 1].items()
        if str(value).strip() == "Mean score"
    )
    year_row = header_row - 1
    columns = []
    for column in frame.columns:
        label = frame.at[year_row, column]
        match = re.fullmatch(r"PISA (\d{4})", str(label).strip())
        if match and str(frame.at[header_row, column]).strip() == "Mean score":
            columns.append((column, int(match.group(1))))

    records = []
    for _, row in frame.iloc[header_row + 1 :].iterrows():
        country = PISA_COUNTRIES.get(str(row.iloc[0]).strip().rstrip("*"))
        if country is None:
            continue
        code, name = country
        for column, year in columns:
            number = _json_number(row[column])
            if number is None:
                continue
            records.append(
                {
                    "REF_AREA": code,
                    "country": name,
                    "TIME_PERIOD": year,
                    "OBS_VALUE": number,
                }
            )
    return pd.DataFrame.from_records(records)


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


def _year(value: object) -> int | None:
    text = str(value).strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    return int(text[:4])


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
        if text in {"", ":", "m", "m "}:
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
    OecdImporter().run()


if __name__ == "__main__":
    main()
