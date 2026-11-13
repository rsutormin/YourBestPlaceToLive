# Copyright (c) 2026 Roman Sutormin. MIT License.

"""Import weather-day counts from the Open-Meteo historical archive.

Each country is requested on its own, at the center of its capital city.
The five most recent complete years are counted with fixed thresholds, then
divided by five so each JSON file stores the average days per year.
Open-Meteo republishes the archive under CC BY 4.0.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import openmeteo_requests
import pandas as pd
import requests_cache
from openmeteo_requests.Client import OpenMeteoRequestsError
from retry_requests import retry

DEFAULT_START_YEAR = 2021
YEAR_COUNT = 5
SOUTH_POLE = (-90.0, 0.0)
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
MIN_DAYS = 360

# Thresholds from the Open-Meteo daily example. Sunshine is the middle of the
# usual 6–8 hour rule. A day counts when the value reaches the threshold.
SUNSHINE_SECONDS = 7.0 * 3600
RAIN_MM = 1.0
SNOW_CM = 0.5
HEAT_CELSIUS = 30.0
COLD_CELSIUS = 0.0
WIND_KMH = 60.0

DAILY_VARIABLES = (
    "temperature_2m_max",
    "rain_sum",
    "snowfall_sum",
    "wind_gusts_10m_max",
    "sunshine_duration",
    "temperature_2m_min",
)

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "climate",
        "name": "Climate",
        "indicators": (
            {
                "key": "sunny_days",
                "code": "sunshine_duration",
                "name": "Climate: Sunny days",
                "unit": "days",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Average number of days per year, over the five most recent full years, when the sun shines for at least seven hours. Counts use daily sunshine duration from the Open-Meteo historical archive, which republishes ECMWF ERA5 under the CC BY 4.0 license.",
            },
            {
                "key": "rainy_days",
                "code": "rain_sum",
                "name": "Climate: Rainy days",
                "unit": "days",
                "reversed_scale": True,
                "importance": 0.0,
                "summary": "Average number of days per year, over the five most recent full years, with at least one millimetre of rain. Counts use daily rainfall from the Open-Meteo historical archive, which republishes ECMWF ERA5 under the CC BY 4.0 license.",
            },
            {
                "key": "snowy_days",
                "code": "snowfall_sum",
                "name": "Climate: Snowy days",
                "unit": "days",
                "reversed_scale": True,
                "importance": 0.0,
                "summary": "Average number of days per year, over the five most recent full years, with at least half a centimetre of snow. Counts use daily snowfall from the Open-Meteo historical archive, which republishes ECMWF ERA5 under the CC BY 4.0 license.",
            },
            {
                "key": "extreme_heat_days",
                "code": "temperature_2m_max",
                "name": "Climate: Extreme heat days",
                "unit": "days",
                "reversed_scale": True,
                "importance": 0.5,
                "summary": "Average number of days per year, over the five most recent full years, when the temperature reaches at least 30 degrees Celsius. Counts use the daily maximum temperature from the Open-Meteo historical archive, which republishes ECMWF ERA5 under the CC BY 4.0 license.",
            },
            {
                "key": "extreme_cold_days",
                "code": "temperature_2m_min",
                "name": "Climate: Extreme cold days",
                "unit": "days",
                "reversed_scale": True,
                "importance": 0.5,
                "summary": "Average number of days per year, over the five most recent full years, when the temperature falls to 0 degrees Celsius or below. Counts use the daily minimum temperature from the Open-Meteo historical archive, which republishes ECMWF ERA5 under the CC BY 4.0 license.",
            },
            {
                "key": "extreme_wind_days",
                "code": "wind_gusts_10m_max",
                "name": "Climate: Extreme wind days",
                "unit": "days",
                "reversed_scale": True,
                "importance": 0.25,
                "summary": "Average number of days per year, over the five most recent full years, when wind gusts reach at least 60 kilometres per hour. Counts use the daily maximum gust from the Open-Meteo historical archive, which republishes ECMWF ERA5 under the CC BY 4.0 license.",
            },
        ),
    },
)


@dataclass(frozen=True)
class CountryPoint:
    """A country sampled at the center of its capital city."""

    code: str
    name: str
    latitude: float
    longitude: float
    capital: str = ""


class OpenMeteoImporter:
    """Download daily archive weather and store one JSON file per day-count metric."""

    def __init__(
        self,
        start_year: int = DEFAULT_START_YEAR,
        end_year: int | None = None,
        output_dir: Path | None = None,
        include_series: bool = False,
        countries: list[CountryPoint] | None = None,
        countries_path: Path | None = None,
        cache_path: Path | None = None,
    ) -> None:
        if end_year is None:
            end_year = datetime.now(timezone.utc).year
        if end_year < start_year:
            raise ValueError(f"end_year {end_year} is before start_year {start_year}")
        root = _repo_root()
        self.start_year = start_year
        self.end_year = end_year
        self.output_dir = output_dir or root / "data"
        self.include_series = include_series
        self.cache_path = cache_path or root / "processes" / ".cache" / "open-meteo"
        self.countries = countries if countries is not None else load_countries(
            countries_path or root / "frontend" / "src" / "world-countries.json",
            geocode=lambda capital, country_code: geocode_capital(capital, country_code, self.cache_path),
        )

    @property
    def years(self) -> list[int]:
        return recent_full_years()

    def fetch_frames(self) -> dict[str, dict[int, pd.DataFrame]]:
        """Download five complete years for one country at a time."""
        client = _client(self.cache_path)
        years = self.years
        frames: dict[str, dict[int, pd.DataFrame]] = {}
        total = len(self.countries)
        for index, country in enumerate(self.countries, start=1):
            print(
                f"open-meteo {years[0]}-{years[-1]} {index}/{total} {country.code} {country.name} ({country.capital})",
                flush=True,
            )
            frame = _fetch_country(client, country, years[0], years[-1])
            if frame is None:
                continue
            by_year = _split_years(frame, years)
            if by_year:
                frames[country.code] = by_year
        return frames

    def to_documents(self) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric."""
        counts = _counts(self.fetch_frames())
        names = {country.code: country.name for country in self.countries}
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                key = indicator["key"]
                series = []
                for year in self.years:
                    data = [
                        {"country": names[code], "code": code, "value": values[key]}
                        for code, values in sorted(
                            (
                                (code, year_counts)
                                for (code, count_year), year_counts in counts.items()
                                if count_year == year and code in names and key in year_counts
                            ),
                            key=lambda item: (names[item[0]].casefold(), item[0]),
                        )
                    ]
                    series.append({"year": year, "count": len(data), "data": data})
                latest = _average_rows(counts, names, key, self.years)
                document = {
                    "metadata": {
                        "source": "Open-Meteo",
                        "scope": "World",
                        "database": "ERA5",
                        "url": "https://open-meteo.com/",
                        "code": indicator["code"],
                        "key": key,
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
                self._year_counts.append((key, indicator["code"], series))
                documents.append((key, document))
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
        """Fetch the indicators and write one JSON file per metric into ``data/``.

        Each finished country is appended to ``<metric>.json.tmp`` and flushed.
        A later run loads those files and skips countries that were already saved.
        The temporary files are deleted after the JSON outputs are written.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        indicators = _indicators()
        saved = {indicator["key"]: _load_checkpoint(self._checkpoint_path(indicator["key"])) for indicator in indicators}
        done = _saved_codes(saved)
        years = self.years
        client = _client(self.cache_path)
        handles = {
            indicator["key"]: self._checkpoint_path(indicator["key"]).open("a", encoding="utf-8")
            for indicator in indicators
        }
        total = len(self.countries)
        try:
            for index, country in enumerate(self.countries, start=1):
                label = f"open-meteo {years[0]}-{years[-1]} {index}/{total} {country.code} {country.name} ({country.capital})"
                if country.code in done:
                    print(f"{label} already saved", flush=True)
                    continue
                print(label, flush=True)
                frame = _fetch_country(client, country, years[0], years[-1])
                if frame is None:
                    continue
                rows = _country_rows(country, _split_years(frame, years), years)
                if rows is None:
                    continue
                for indicator in indicators:
                    key = indicator["key"]
                    _append_checkpoint(handles[key], rows[key])
                    saved[key].append(rows[key])
        finally:
            for handle in handles.values():
                handle.close()
        documents = _documents_from_rows(indicators, saved)
        paths = self.save(documents)
        for indicator in indicators:
            self._checkpoint_path(indicator["key"]).unlink(missing_ok=True)
        for indicator in indicators:
            print(f"{indicator['key']} ({indicator['code']})")
            print(f"  saved: {len(_dedupe_rows(saved[indicator['key']]))}")
        return paths

    def _checkpoint_path(self, key: str) -> Path:
        return self.output_dir / f"{key}.json.tmp"


def load_countries(
    path: Path,
    capitals_path: Path | None = None,
    geocode=None,
) -> list[CountryPoint]:
    """Read map countries and locate each one at its capital city center."""
    capitals = json.loads((capitals_path or _default_capitals_path()).read_text(encoding="utf-8"))
    if geocode is None:
        geocode = geocode_capital
    document = json.loads(path.read_text(encoding="utf-8"))
    countries = []
    for feature in document["features"]:
        properties = feature.get("properties") or {}
        code = properties.get("iso_a3")
        name = properties.get("name")
        if not isinstance(code, str) or len(code) != 3 or not code.isalpha() or not name:
            continue
        # Antarctica has no capital, so the sample point is the South Pole.
        if code == "ATA":
            latitude, longitude = SOUTH_POLE
            countries.append(CountryPoint(code, str(name), latitude, longitude, "South Pole"))
            continue
        capital = capitals.get(code)
        if not capital:
            print(f"open-meteo skip {code} {name}: no capital", flush=True)
            continue
        country_code = properties.get("iso_a2") or ""
        if country_code == "-99":
            country_code = ""
        point = geocode(capital, country_code)
        if point is None:
            print(f"open-meteo skip {code} {name}: no coordinates for {capital}", flush=True)
            continue
        latitude, longitude = point
        countries.append(
            CountryPoint(code, str(name), round(latitude, 4), round(longitude, 4), capital)
        )
    return sorted(countries, key=lambda country: (country.name.casefold(), country.code))


def recent_full_years(today: date | None = None, count: int = YEAR_COUNT) -> list[int]:
    """The most recent calendar years that have already finished."""
    today = today or datetime.now(timezone.utc).date()
    last = today.year - 1
    return list(range(last - count + 1, last + 1))


def geocode_capital(
    capital: str,
    country_code: str,
    cache_path: Path | None = None,
) -> tuple[float, float] | None:
    """Ask Open-Meteo for the center of this capital in its own country."""
    session = _geocode_session(cache_path)
    response = session.get(
        GEOCODE_URL,
        params={"name": capital, "count": 50, "language": "en", "format": "json"},
        timeout=30,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    return capital_coordinate(results, country_code)


def capital_coordinate(results: list[dict], country_code: str) -> tuple[float, float] | None:
    """Pick the capital place, preferring the official capital over a larger city."""
    if country_code:
        matches = [row for row in results if row.get("country_code") == country_code]
    else:
        matches = list(results)
    if not matches:
        return None
    best = min(
        matches,
        key=lambda row: (row.get("feature_code") != "PPLC", -(row.get("population") or 0)),
    )
    latitude = best.get("latitude")
    longitude = best.get("longitude")
    if latitude is None or longitude is None:
        return None
    return float(latitude), float(longitude)


def _default_capitals_path() -> Path:
    return Path(__file__).resolve().parent / "capitals.json"


def _geocode_session(cache_path: Path | None):
    if cache_path is None:
        import requests

        return requests.Session()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    return requests_cache.CachedSession(str(cache_path), expire_after=-1)


def metric_counts(frame: pd.DataFrame) -> dict[str, int] | None:
    """Count threshold days. A short or partial year is left out."""
    if len(frame) < MIN_DAYS:
        return None
    return {
        "sunny_days": int((frame["sunshine_sec"] >= SUNSHINE_SECONDS).sum()),
        "rainy_days": int((frame["rain"] >= RAIN_MM).sum()),
        "snowy_days": int((frame["snow"] >= SNOW_CM).sum()),
        "extreme_heat_days": int((frame["temp_max"] >= HEAT_CELSIUS).sum()),
        "extreme_cold_days": int((frame["temp_min"] <= COLD_CELSIUS).sum()),
        "extreme_wind_days": int((frame["wind_gusts"] >= WIND_KMH).sum()),
    }


def _client(cache_path: Path) -> openmeteo_requests.Client:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_session = requests_cache.CachedSession(str(cache_path), expire_after=-1)
    retry_session = retry(
        cache_session,
        retries=5,
        backoff_factor=0.2,
        status_to_retry=(429, 500, 502, 504),
    )
    return openmeteo_requests.Client(session=retry_session)


def _fetch_country(
    client: openmeteo_requests.Client,
    country: CountryPoint,
    start_year: int,
    end_year: int,
) -> pd.DataFrame | None:
    params = {
        "latitude": country.latitude,
        "longitude": country.longitude,
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
        "daily": list(DAILY_VARIABLES),
        "timezone": "UTC",
    }
    try:
        responses = client.weather_api(ARCHIVE_URL, params=params)
    except OpenMeteoRequestsError as error:
        print(f"open-meteo skip {country.code} {country.name}: {error}", flush=True)
        return None
    if len(responses) != 1:
        print(f"open-meteo skip {country.code} {country.name}: unexpected response", flush=True)
        return None
    return _daily_frame(responses[0])


def _daily_frame(response: object) -> pd.DataFrame:
    daily = response.Daily()  # type: ignore[attr-defined]
    if daily is None:
        return pd.DataFrame(columns=["date", "temp_max", "rain", "snow", "wind_gusts", "sunshine_sec", "temp_min"])
    variables = [daily.Variables(index).ValuesAsNumpy() for index in range(len(DAILY_VARIABLES))]
    length = min(len(variable) for variable in variables)
    dates = pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left",
    )
    length = min(length, len(dates))
    return pd.DataFrame(
        {
            "date": dates[:length],
            "temp_max": variables[0][:length],
            "rain": variables[1][:length],
            "snow": variables[2][:length],
            "wind_gusts": variables[3][:length],
            "sunshine_sec": variables[4][:length],
            "temp_min": variables[5][:length],
        }
    )


def _counts(frames: dict[str, dict[int, pd.DataFrame]]) -> dict[tuple[str, int], dict[str, int]]:
    counts: dict[tuple[str, int], dict[str, int]] = {}
    for code, years in frames.items():
        for year, frame in years.items():
            values = metric_counts(frame)
            if values is not None:
                counts[(code, year)] = values
    return counts


def _split_years(frame: pd.DataFrame, years: list[int]) -> dict[int, pd.DataFrame]:
    if frame.empty or "date" not in frame.columns:
        return {}
    dated = frame.copy()
    dated["_year"] = pd.to_datetime(dated["date"], utc=True).dt.year
    wanted = set(years)
    return {
        int(year): group.drop(columns="_year")
        for year, group in dated.groupby("_year")
        if int(year) in wanted
    }


def _indicators() -> list[dict]:
    return [indicator for category in CATEGORIES for indicator in category["indicators"]]


def _load_checkpoint(path: Path) -> list[dict]:
    """Read saved country rows. A trailing partial line left by a crash is ignored."""
    if not path.is_file():
        return []
    rows = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        code = row.get("code")
        if not isinstance(code, str) or code in seen:
            continue
        seen.add(code)
        rows.append(row)
    return rows


def _saved_codes(saved: dict[str, list[dict]]) -> set[str]:
    """Countries present in every metric file. A partial country is fetched again."""
    code_sets = [{row["code"] for row in rows} for rows in saved.values()]
    if not code_sets:
        return set()
    return set.intersection(*code_sets)


def _append_checkpoint(handle, row: dict) -> None:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _country_rows(
    country: CountryPoint,
    by_year: dict[int, pd.DataFrame],
    years: list[int],
) -> dict[str, dict] | None:
    counts = _counts({country.code: by_year})
    names = {country.code: country.name}
    rows = {}
    for indicator in _indicators():
        averaged = _average_rows(counts, names, indicator["key"], years)
        if not averaged:
            return None
        rows[indicator["key"]] = averaged[0]
    return rows


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for row in rows:
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        unique.append(row)
    return sorted(unique, key=lambda row: (row["country"].casefold(), row["code"]))


def _documents_from_rows(indicators: list[dict], saved: dict[str, list[dict]]) -> list[tuple[str, dict]]:
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    category_names = {
        indicator["key"]: category["name"]
        for category in CATEGORIES
        for indicator in category["indicators"]
    }
    documents = []
    for indicator in indicators:
        data = _dedupe_rows(saved[indicator["key"]])
        documents.append(
            (
                indicator["key"],
                {
                    "metadata": {
                        "source": "Open-Meteo",
                        "scope": "World",
                        "database": "ERA5",
                        "url": "https://open-meteo.com/",
                        "code": indicator["code"],
                        "key": indicator["key"],
                        "description": indicator["name"],
                        "summary": indicator["summary"],
                        "category": category_names[indicator["key"]],
                        "units": indicator["unit"],
                        "reversedScale": indicator["reversed_scale"],
                        "importance": indicator["importance"],
                        "dataSize": len(data),
                        "retrievedAt": retrieved_at,
                    },
                    "data": data,
                },
            )
        )
    return documents


def _average_rows(
    counts: dict[tuple[str, int], dict[str, int]],
    names: dict[str, str],
    key: str,
    years: list[int],
) -> list[dict]:
    """Mean of the yearly counts. A country missing any of the five years is left out."""
    rows = []
    end_year = years[-1]
    for code, name in sorted(names.items(), key=lambda item: (item[1].casefold(), item[0])):
        total = 0
        for year in years:
            values = counts.get((code, year))
            if values is None or key not in values:
                total = -1
                break
            total += values[key]
        if total < 0:
            continue
        rows.append(
            {
                "country": name,
                "code": code,
                "value": round(total / len(years), 4),
                "year": end_year,
            }
        )
    return rows


def _log_counts(year_counts: list[tuple[str, str, list[dict]]]) -> None:
    for key, code, series in year_counts:
        print(f"{key} ({code})")
        for entry in series:
            print(f"  {entry['year']}: {entry['count']}")


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "data").is_dir() and (parent / "processes").is_dir():
            return parent
    raise FileNotFoundError(
        "Could not locate the repository root (expected data/ and processes/)."
    )


def main() -> None:
    OpenMeteoImporter().run()


if __name__ == "__main__":
    main()
