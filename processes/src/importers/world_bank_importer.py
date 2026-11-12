"""Import World Bank Open Data series into frontend JSON.

Purchasing power, inflation, public spending, homicides, and communications
are loaded together with wbgapi for every year from 2020 through the current
year. The cost-of-living burden is the exception: its two input series are
read one year at a time from the paged indicator API, for the two completed
years before the current year, and each page is cached until the export
finishes. Each metric is written as its own JSON file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import wbgapi as wb

# Regular series. The current year is included; wbgapi omits a period the
# catalog does not have yet.
DEFAULT_START_YEAR = 2020
# Cost-of-living inputs. The current year is omitted because that request
# returns a non-JSON error, and only the two completed years are fetched.
COST_BURDEN_YEAR_COUNT = 2
# One year per request. A date range such as 2020:2025 makes this endpoint
# return 502.
PAGE_CACHE_DIRNAME = ".world-bank-pages"
PAGE_SIZE = 50
PAGE_TIMEOUT_SECONDS = 30
PAGE_ATTEMPTS = 10
RETRY_WAIT_SECONDS = 15
RETRYABLE_STATUS = {502, 503, 504}
INDICATOR_URL = "https://api.worldbank.org/v2/country/all/indicator/{code}"
# PA.NUS.GDP.PLI is published with the United States equal to 100.
# The retired ratio series used 1, which is the scale this metric keeps.
PRICE_LEVEL_INDEX_BASE = 100

# Stable app keys sit next to the World Bank series codes. Names and units are
# the published WDI labels; keys stay fixed even if those labels change.
# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
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
                "importance": 0.75,
                "summary": "Gross domestic product per person, converted to current international dollars so prices are comparable across countries. The World Bank compiles it from national accounts in the World Development Indicators.",
            },
            {
                "code": "FP.CPI.TOTL.ZG",
                "key": "inflation_rate",
                "name": "Inflation, consumer prices",
                "unit": "annual %",
                "reversed_scale": True,
                "importance": 0.5,
                "summary": "Annual percentage change in consumer prices, showing how fast the cost of a typical household basket rises. National statistical offices report the index, and the World Bank republishes it.",
            },
            {
                "code": "PA.NUS.GDP.PLI / NY.GDP.PCAP.CD",
                "key": "cost_burden_index",
                "name": "Relative cost-of-living burden",
                "unit": "per $1,000 of GDP per capita",
                "reversed_scale": True,
                "importance": 1.0,
                "price_level": "PA.NUS.GDP.PLI",
                "gdp_per_capita": "NY.GDP.PCAP.CD",
                "summary": "Relative cost of living: the World Bank price level index, with the United States set to 1, divided by GDP per capita in current US dollars and scaled by 1,000. A higher value means local prices claim more of average income.",
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
                "importance": 0.5,
                "summary": "Public spending on health by general government, measured as a share of gross domestic product. Figures come from the World Health Organization and are published in the World Bank indicators.",
            },
            {
                "code": "SE.XPD.TOTL.GD.ZS",
                "key": "government_education_expenditure_gdp",
                "name": "Government expenditure on education, total",
                "unit": "% of GDP",
                "reversed_scale": False,
                "importance": 0.5,
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
                "importance": 1.0,
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
                "importance": 0.25,
                "summary": "Share of people who used the internet during the past three months. National surveys and operator data are gathered by the International Telecommunication Union and published by the World Bank.",
            },
            {
                "code": "IT.NET.BBND.P2",
                "key": "fixed_broadband_subscriptions",
                "name": "Fixed broadband subscriptions",
                "unit": "per 100 people",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Fixed subscriptions that deliver broadband internet to homes and businesses, counted per 100 people. Telecom operators report the lines to the International Telecommunication Union, which the World Bank republishes.",
            },
            {
                "code": "IT.CEL.SETS.P2",
                "key": "mobile_subscriptions",
                "name": "Mobile cellular subscriptions",
                "unit": "per 100 people",
                "reversed_scale": False,
                "importance": 0.0,
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
        keys: Collection[str] | None = None,
        debug: bool = False,
    ) -> None:
        if end_year is None:
            end_year = datetime.now(timezone.utc).year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} is before start_year {start_year}")
        self.start_year = start_year
        self.end_year = end_year
        # The cost-burden window does not follow the bulk year range.
        self.cost_end_year = datetime.now(timezone.utc).year - 1
        self.cost_start_year = self.cost_end_year - COST_BURDEN_YEAR_COUNT + 1
        self.output_dir = output_dir or _repo_root() / "data"
        self.include_series = include_series
        self.keys = _checked_keys(keys)
        self.debug = debug

    @property
    def years(self) -> range:
        return range(self.start_year, self.end_year + 1)

    @property
    def cost_years(self) -> range:
        return range(self.cost_start_year, self.cost_end_year + 1)

    def fetch(self) -> pd.DataFrame:
        """Return the wide World Bank frame for every configured series.

        Regular series come from one wbgapi request. Cost-burden inputs come
        from the paged indicator API. Regional aggregates are left out of both.
        """
        original_get = requests.get
        if self.debug:
            requests.get = _debug_get(original_get)
        try:
            return self._fetch_frames()
        finally:
            requests.get = original_get

    def _fetch_frames(self) -> pd.DataFrame:
        frames = []
        bulk = _bulk_series_codes(self.keys)
        if bulk:
            frames.append(self._fetch_bulk(bulk))
        paged = _paged_series_codes(self.keys)
        if paged:
            frames.append(self._fetch_paged(paged))
        frames = [frame for frame in frames if frame is not None and not frame.empty]
        if not frames:
            return pd.DataFrame()
        if len(frames) == 1:
            return frames[0]
        return pd.concat(frames)

    def _fetch_bulk(self, codes: list[str]) -> pd.DataFrame:
        """Load every regular series for the full year range in one request."""
        _log(f"world-bank {self.start_year}-{self.end_year}: loading {', '.join(codes)}")
        started = time.perf_counter()
        frame = wb.data.DataFrame(
            codes,
            economy="all",
            time=self.years,
            labels=True,
            numericTimeKeys=True,
            skipAggs=True,
        )
        _log(f"world-bank bulk: {len(frame)} rows in {_seconds(started)}")
        return frame

    def _fetch_paged(self, codes: list[str]) -> pd.DataFrame:
        """Load cost-burden inputs one year and one page at a time."""
        _log(
            f"world-bank {self.cost_start_year}-{self.cost_end_year}: loading countries"
        )
        economies = wb.economy.DataFrame(skipAggs=True)
        economy_ids = set(economies.index)
        _log(f"world-bank countries: {len(economy_ids)}")
        frames = []
        for index, code in enumerate(codes, start=1):
            _log(f"world-bank {index}/{len(codes)} {code}")
            started = time.perf_counter()
            frame = _fetch_series_frame(
                code,
                self.cost_start_year,
                self.cost_end_year,
                self.cost_years,
                economy_ids,
                index,
                len(codes),
                self._page_cache_dir(),
            )
            _log(f"world-bank {index}/{len(codes)} {code}: {len(frame)} rows in {_seconds(started)}")
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        if len(frames) == 1:
            return frames[0]
        return pd.concat(frames)

    def to_documents(self, frame: pd.DataFrame) -> list[tuple[str, dict]]:
        """Build one metadata-plus-series document per metric, for every requested year."""
        values, country_names, _series_names = _lookup(frame)
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                if self.keys is not None and indicator["key"] not in self.keys:
                    continue
                code = indicator["code"]
                years = self.cost_years if _is_cost_burden(indicator) else self.years
                if _is_cost_burden(indicator):
                    series = _cost_burden_series(
                        values,
                        country_names,
                        indicator["price_level"],
                        indicator["gdp_per_capita"],
                        years,
                    )
                else:
                    series = []
                    for year in years:
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
                        "importance": indicator["importance"],
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
            _log(f"world-bank saved {path.name} ({document['metadata']['dataSize']} countries)")
            paths.append(path)
        return paths

    def run(self) -> list[Path]:
        """Fetch the indicators and write one JSON file per metric into ``data/``."""
        if self.keys is None:
            _log(f"world-bank {self.start_year}-{self.end_year}: starting")
        else:
            _log(
                f"world-bank {self.start_year}-{self.end_year}: "
                f"starting {', '.join(self.keys)}"
            )
        frame = self.fetch()
        _log(f"world-bank fetch complete: {len(frame)} rows")
        documents = self.to_documents(frame)
        paths = self.save(documents)
        paged = _paged_series_codes(self.keys)
        removed = _clear_page_cache(self._page_cache_dir(), paged) if paged else 0
        if removed:
            _log(f"world-bank removed {removed} stored pages")
        _log_counts(self._year_counts)
        _log(f"world-bank done: {len(paths)} files in {self.output_dir}")
        return paths

    def _page_cache_dir(self) -> Path:
        return self.output_dir / PAGE_CACHE_DIRNAME


def _debug_get(original_get):
    """Print the full URL, then perform the request."""

    def getter(url, *args, **kwargs):
        full = requests.Request("GET", url, params=kwargs.get("params")).prepare().url
        _log(f"world-bank GET {full}")
        return original_get(url, *args, **kwargs)

    return getter


def _fetch_series_frame(
    code: str,
    start_year: int,
    end_year: int,
    years: range,
    economy_ids: set[str],
    position: int,
    total: int,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Download one indicator, one year at a time, logging page progress.

    Each finished page is written under ``cache_dir`` so a later run can skip
    it. The directory is removed after the metric JSON files are saved.
    """
    kept = []
    year_list = list(range(start_year, end_year + 1))
    year_count = len(year_list)
    for year_index, year in enumerate(year_list):
        page = 1
        pages = 1
        while page <= pages:
            stored = _read_stored_page(cache_dir, code, year, page)
            if stored is None:
                _log(f"world-bank {position}/{total} {code}: fetching {year} page {page}")
                header, rows = _indicator_page(code, year, page)
                _store_page(cache_dir, code, year, page, header, rows)
            else:
                header, rows = stored
                _log(f"world-bank {position}/{total} {code}: {year} page {page} stored")
            pages = int(header["pages"])
            for row in rows:
                if row.get("countryiso3code") in economy_ids:
                    kept.append(row)
            if pages <= 0:
                percent = (year_index + 1) * 100 // year_count
                _log(f"world-bank {position}/{total} {code}: {year} page 1/1 ({percent}%)")
                break
            percent = (year_index * pages + page) * 100 // (year_count * pages)
            _log(
                f"world-bank {position}/{total} {code}: "
                f"{year} page {page}/{pages} ({percent}%)"
            )
            page += 1
    return _series_frame(code, kept, years)


def _page_cache_path(cache_dir: Path, code: str, year: int, page: int) -> Path:
    return cache_dir / f"{code}-{year}-{page}.json"


def _read_stored_page(
    cache_dir: Path | None,
    code: str,
    year: int,
    page: int,
) -> tuple[dict, list] | None:
    if cache_dir is None:
        return None
    path = _page_cache_path(cache_dir, code, year, page)
    if not path.is_file():
        return None
    try:
        return _page_payload(json.loads(path.read_text(encoding="utf-8")), code, year, page)
    except (OSError, json.JSONDecodeError, RuntimeError, TypeError, KeyError, ValueError):
        return None


def _store_page(
    cache_dir: Path | None,
    code: str,
    year: int,
    page: int,
    header: dict,
    rows: list,
) -> None:
    if cache_dir is None:
        return
    path = _page_cache_path(cache_dir, code, year, page)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".json.partial")
    with partial.open("w", encoding="utf-8") as handle:
        json.dump([header, rows], handle)
        handle.flush()
        os.fsync(handle.fileno())
    partial.replace(path)


def _clear_page_cache(cache_dir: Path, codes: list[str]) -> int:
    """Delete stored pages for the series this run exported."""
    if not cache_dir.is_dir():
        return 0
    prefixes = tuple(f"{code}-" for code in codes)
    stored = [
        path
        for path in cache_dir.iterdir()
        if prefixes and path.name.startswith(prefixes)
    ]
    for path in stored:
        path.unlink()
    if not any(cache_dir.iterdir()):
        cache_dir.rmdir()
    return len(stored)


def _indicator_page(code: str, year: int, page: int) -> tuple[dict, list]:
    """One page of ``/v2/country/all/indicator/{code}?date={year}``.

    A page often answers in under a second and sometimes does not answer at
    all. Each attempt waits 30 seconds. After a failure the next attempt waits
    15 seconds, and that pause doubles after every further failure.
    """
    last_error: Exception | None = None
    for attempt in range(1, PAGE_ATTEMPTS + 1):
        try:
            response = requests.get(
                INDICATOR_URL.format(code=code),
                params={
                    "date": year,
                    "format": "json",
                    "per_page": PAGE_SIZE,
                    "page": page,
                },
                timeout=PAGE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return _page_payload(response.json(), code, year, page)
        except (requests.Timeout, requests.ConnectionError) as error:
            last_error = error
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status not in RETRYABLE_STATUS:
                raise
            last_error = error
        if attempt == PAGE_ATTEMPTS:
            raise last_error
        wait = _retry_wait_seconds(attempt)
        _log(
            f"world-bank {code} {year} page {page}: "
            f"attempt {attempt}/{PAGE_ATTEMPTS} failed, waiting {wait}s"
        )
        time.sleep(wait)
    raise last_error


def _retry_wait_seconds(failed_attempt: int) -> int:
    """Pause after a failed attempt. The first pause is 15 seconds."""
    return RETRY_WAIT_SECONDS * 2 ** (failed_attempt - 1)


def _page_payload(payload: object, code: str, year: int, page: int) -> tuple[dict, list]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError(f"World Bank returned an unexpected payload for {code} {year} page {page}")
    header = payload[0]
    if "message" in header:
        message = header["message"][0]
        detail = message.get("value") or message.get("key") or message
        raise RuntimeError(f"World Bank rejected {code} {year} page {page}: {detail}")
    rows = payload[1] if len(payload) > 1 and payload[1] else []
    return header, rows


def _series_frame(code: str, rows: list[dict], years: range) -> pd.DataFrame:
    """Wide country-by-year frame matching the shape ``_lookup`` reads."""
    by_country: dict[str, dict] = {}
    for row in rows:
        year = int(row["date"])
        if year not in years:
            continue
        iso3 = row["countryiso3code"]
        record = by_country.get(iso3)
        if record is None:
            record = {
                "economy": iso3,
                "series": code,
                "Country": row["country"]["value"],
                "Series": row["indicator"]["value"],
            }
            by_country[iso3] = record
        record[year] = row["value"]

    year_list = list(years)
    if not by_country:
        frame = pd.DataFrame(columns=["Country", "Series", *year_list])
        frame.index = pd.MultiIndex.from_arrays([[], []], names=["economy", "series"])
        return frame

    frame = pd.DataFrame(by_country.values()).set_index(["economy", "series"])
    for year in year_list:
        if year not in frame.columns:
            frame[year] = None
    return frame[["Country", "Series", *year_list]]


def _metric_keys() -> list[str]:
    return [
        indicator["key"]
        for category in CATEGORIES
        for indicator in category["indicators"]
    ]


def _checked_keys(keys: Collection[str] | None) -> list[str] | None:
    """Return the requested metric keys, or None when every metric should run."""
    if keys is None:
        return None
    selected = list(keys)
    unknown = [key for key in selected if key not in set(_metric_keys())]
    if unknown:
        known = ", ".join(_metric_keys())
        raise ValueError(f"Unknown World Bank metric keys: {', '.join(unknown)}. Known keys: {known}")
    return selected


def _is_cost_burden(indicator: dict) -> bool:
    return bool(indicator.get("price_level") and indicator.get("gdp_per_capita"))


def _selected_keys(keys: Collection[str] | None) -> set[str] | None:
    return None if keys is None else set(keys)


def _bulk_series_codes(keys: Collection[str] | None = None) -> list[str]:
    """Series loaded together by wbgapi. The cost-burden inputs are not included."""
    selected = _selected_keys(keys)
    codes = []
    for category in CATEGORIES:
        for indicator in category["indicators"]:
            if selected is not None and indicator["key"] not in selected:
                continue
            if not _is_cost_burden(indicator):
                codes.append(indicator["code"])
    return codes


def _paged_series_codes(keys: Collection[str] | None = None) -> list[str]:
    """Input series of the cost-burden metric, fetched page by page."""
    selected = _selected_keys(keys)
    codes = []
    for category in CATEGORIES:
        for indicator in category["indicators"]:
            if selected is not None and indicator["key"] not in selected:
                continue
            if _is_cost_burden(indicator):
                codes.extend((indicator["price_level"], indicator["gdp_per_capita"]))
    return list(dict.fromkeys(codes))


def _series_codes(keys: Collection[str] | None = None) -> list[str]:
    """World Bank series codes to download, including inputs of calculated metrics."""
    return list(dict.fromkeys([*_bulk_series_codes(keys), *_paged_series_codes(keys)]))


def _cost_burden(price_level: float | None, gdp_per_capita: float | None) -> float | None:
    """``(price level / GDP per capita) * 1000``, or nothing when that is undefined."""
    if (
        price_level is None
        or gdp_per_capita is None
        or not math.isfinite(price_level)
        or not math.isfinite(gdp_per_capita)
        or gdp_per_capita == 0
    ):
        return None
    return _json_number(price_level / gdp_per_capita * 1000)


def _cost_burden_series(
    values: dict[tuple[str, str, int], float | None],
    country_names: dict[str, str],
    price_code: str,
    gdp_code: str,
    years: range,
) -> list[dict]:
    """One row per country-year where both inputs exist and GDP is not zero."""
    series = []
    for year in years:
        present = {
            country
            for (country, code, value_year) in values
            if value_year == year and code in {price_code, gdp_code}
        }
        data = []
        for country in sorted(present, key=lambda code: (country_names.get(code, code).casefold(), code)):
            price_level = values.get((country, price_code, year))
            if price_level is not None:
                price_level = price_level / PRICE_LEVEL_INDEX_BASE
            burden = _cost_burden(
                price_level,
                values.get((country, gdp_code, year)),
            )
            if burden is None:
                continue
            data.append(
                {
                    "country": country_names.get(country, country),
                    "code": country,
                    "value": burden,
                }
            )
        series.append({"year": year, "count": len(data), "data": data})
    return series


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


def _log(message: str) -> None:
    print(message, flush=True)


def _seconds(started: float) -> str:
    return f"{time.perf_counter() - started:.1f}s"


def _log_counts(year_counts: list[tuple[str, str, list[dict]]]) -> None:
    for key, code, series in year_counts:
        _log(f"{key} ({code})")
        for entry in series:
            _log(f"  {entry['year']}: {entry['count']}")


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import World Bank metrics.")
    parser.add_argument(
        "--keys",
        nargs="*",
        metavar="KEY",
        help="Metric keys to import. Omit this option to import every metric.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print each World Bank URL before it is fetched.",
    )
    args = parser.parse_args(argv)
    WorldBankImporter(keys=args.keys, debug=args.debug).run()


if __name__ == "__main__":
    main()
