"""Import Wikipedia country tables into frontend JSON.

Each article's country table is chosen by its columns, not by position.
Maintenance banners on a page are also HTML tables, so a fixed index does
not stay pointed at the country list.
"""

from __future__ import annotations

import io
import json
import math
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ARTICLE_URL = "https://en.wikipedia.org/wiki/List_of_countries_by_English-speaking_population"
OPPOSITION_URL = "https://en.wikipedia.org/wiki/Opposition_to_immigration"
IMMIGRANT_URL = "https://en.wikipedia.org/wiki/List_of_sovereign_states_by_immigrant_and_emigrant_population"
USER_AGENT = "YourBestPlaceToLive/0.1 (Wikipedia import)"
ISO3 = re.compile(r"^[A-Z]{3}$")
YEAR = re.compile(r"(?:19|20)\d{2}")
FOOTNOTE = re.compile(r"\s*\[[^\]]*\]")
SURVEY_INTRO = re.compile(r"In\s+((?:19|20)\d{2}),\s+a\s+survey", re.IGNORECASE)

# Wikipedia names that do not match the map files. Territories that share one
# ISO code and are listed separately are left unmapped.
ALIASES = {
    "United States": "USA",
    "Czech Republic": "CZE",
    "Eswatini": "SWZ",
    "Solomon Islands": "SLB",
    "Saint Vincent and the Grenadines": "VCT",
    "U.S. Virgin Islands": "VIR",
    "Saint Lucia": "LCA",
    "Micronesia": "FSM",
    "Saint Kitts and Nevis": "KNA",
    "Cocos (Keeling) Islands": "CCK",
    "Bosnia and Herzegovina": "BIH",
    "Brunei Darussalam": "BRN",
    "Central African Republic": "CAF",
    "Macau": "MAC",
    "Curaçao": "CUW",
    "Curacao": "CUW",
    "Democratic Republic of the Congo": "COD",
    "Dominican Republic": "DOM",
    "Equatorial Guinea": "GNQ",
    "Falkland Islands": "FLK",
    "Vatican City": "VAT",
    "Micronesia (Fed. States of)": "FSM",
    "Republic of Moldova": "MDA",
    "Réunion": "REU",
    "Reunion": "REU",
    "Sint Maarten": "SXM",
    "South Sudan": "SSD",
    "State of Palestine": "PSE",
    "Syrian Arab Republic": "SYR",
    "United Republic of Tanzania": "TZA",
    "United States Virgin Islands": "VIR",
    "Wallis and Futuna Islands": "WLF",
    "Western Sahara": "ESH",
}

# reversed_scale is true when a higher value means worse conditions.
# importance is the default slider weight: 0, 0.25, 0.5, 0.75, or 1.
CATEGORIES = (
    {
        "id": "language",
        "name": "Language",
        "indicators": (
            {
                "key": "english_speaking_population",
                "code": "total_english_speakers_percent",
                "name": "Percent of English-speaking population",
                "unit": "%",
                "reversed_scale": False,
                "importance": 0.75,
                "summary": "Share of people who can speak English, including those who learned it as an additional language. Figures are the total percentages compiled on the English Wikipedia list of countries by English-speaking population.",
                "url": ARTICLE_URL,
                "database": "List of countries by English-speaking population",
                "parser": "english",
            },
        ),
    },
    {
        "id": "immigration",
        "name": "Immigration",
        "indicators": (
            {
                "key": "opposition_to_immigration",
                "code": "fewer_or_no_immigrants_percent",
                "name": "Want fewer or no immigrants",
                "unit": "%",
                "reversed_scale": True,
                "importance": 0.5,
                "summary": "Share of adults who say their country should let in fewer immigrants or none at all. Figures are the fewer-or-none column of the cross-country survey table on the English Wikipedia page about opposition to immigration.",
                "url": OPPOSITION_URL,
                "database": "Opposition to immigration",
                "parser": "opposition",
            },
            {
                "key": "immigrant_population_share",
                "code": "immigrant_percent_of_population",
                "name": "Immigrant share of population",
                "unit": "%",
                "reversed_scale": False,
                "importance": 0.25,
                "summary": "Immigrants as a percentage of each country's resident population. The shares come from the United Nations international migrant stock, as compiled on the English Wikipedia list of states by immigrant and emigrant population.",
                "url": IMMIGRANT_URL,
                "database": "List of sovereign states by immigrant and emigrant population",
                "parser": "immigrant_share",
            },
        ),
    },
)


class WikipediaImporter:
    """Download the Wikipedia country tables and store one JSON file per metric."""

    def __init__(
        self,
        output_dir: Path | None = None,
        include_series: bool = False,
        article_url: str = ARTICLE_URL,
        fallback_year: int | None = None,
    ) -> None:
        self.output_dir = output_dir or _repo_root() / "data"
        self.include_series = include_series
        self.article_url = article_url
        self.fallback_year = fallback_year or datetime.now(timezone.utc).year

    def fetch(self) -> dict[str, pd.DataFrame]:
        """Download each article and return the selected country table by metric key."""
        pages = self._load_pages()
        frames = {}
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                url = self.article_url if indicator["parser"] == "english" else indicator["url"]
                html, tables = pages[url]
                frame, _year = _selected_table(indicator, tables, html, self.fallback_year)
                frames[indicator["key"]] = frame
                _log(f"wikipedia: {indicator['key']} table has {len(frame)} rows")
        return frames

    def to_documents(self, frame: pd.DataFrame | None = None) -> list[tuple[str, dict]]:
        """Build one metadata-plus-data document per metric.

        Passing ``frame`` builds only the English-speaking metric from that
        table, which keeps the table parser testable without downloading.
        """
        pages = None if frame is not None else self._load_pages()
        codes = _country_codes()
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents = []
        self._year_counts = []
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                if frame is not None and indicator["parser"] != "english":
                    continue
                rows = self._rows(indicator, frame, pages, codes)
                series = _series(rows)
                latest = _latest_country_rows(series)
                document = {
                    "metadata": {
                        "source": "Wikipedia",
                        "scope": "World",
                        "database": indicator["database"],
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

    def _load_pages(self) -> dict[str, tuple[str, list[pd.DataFrame]]]:
        pages: dict[str, tuple[str, list[pd.DataFrame]]] = {}
        for category in CATEGORIES:
            for indicator in category["indicators"]:
                url = indicator["url"]
                if indicator["parser"] == "english":
                    url = self.article_url
                if url in pages:
                    continue
                _log(f"wikipedia: downloading {url}")
                started = time.perf_counter()
                html = _download(url)
                _log(f"wikipedia: received {len(html)} characters in {_seconds(started)}")
                pages[url] = (html, pd.read_html(io.StringIO(html)))
        return pages

    def _rows(self, indicator: dict, frame, pages, codes: dict[str, str]) -> list[dict]:
        if indicator["parser"] == "english" and frame is not None:
            return _english_rows(frame, codes, self.fallback_year)
        html, tables = pages[indicator["url"] if indicator["parser"] != "english" else self.article_url]
        selected, year = _selected_table(indicator, tables, html, self.fallback_year)
        if indicator["parser"] == "english":
            return _english_rows(selected, codes, self.fallback_year)
        if indicator["parser"] == "opposition":
            return _fixed_year_rows(selected, codes, _opposition_columns, year, "opposition poll")
        return _fixed_year_rows(selected, codes, _immigrant_columns, year, "immigrant share")

    def save(self, documents: list[tuple[str, dict]]) -> list[Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for key, document in documents:
            path = self.output_dir / f"{key}.json"
            path.write_text(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            _log(f"wikipedia saved {path.name} ({document['metadata']['dataSize']} countries)")
            paths.append(path)
        return paths

    def run(self) -> list[Path]:
        """Fetch the lists and write one JSON file per metric into ``data/``."""
        _log("wikipedia: starting")
        documents = self.to_documents()
        paths = self.save(documents)
        _log_counts(self._year_counts)
        _log(f"wikipedia done: {len(paths)} files in {self.output_dir}")
        return paths


def _selected_table(
    indicator: dict,
    tables: list[pd.DataFrame],
    html: str,
    fallback_year: int,
) -> tuple[pd.DataFrame, int]:
    """Return the country table for one metric and the year that applies to it."""
    if indicator["parser"] == "english":
        return _english_speakers_table(tables), fallback_year
    if indicator["parser"] == "opposition":
        return _opposition_poll_table(tables), _survey_year(html, fallback_year)
    return _immigrant_share_table(tables)


def _english_speakers_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Return the country table that reports the total English-speaking share.

    The live article places maintenance banners ahead of the country list, so
    the list is not a stable index. A usable table names a country column and
    a total-percent column, and most of its percent cells parse as numbers.
    """
    ranked = []
    for index, table in enumerate(tables):
        columns = _percent_columns(table)
        if columns is None:
            continue
        parsed = sum(_percent(value) is not None for value in table[columns[1]])
        if parsed < 10:
            continue
        ranked.append((parsed, index, table))
    if not ranked:
        raise ValueError("Wikipedia page has no English-speaking population table")
    parsed, index, table = max(ranked, key=lambda item: item[0])
    _log(f"wikipedia: table {index} has {parsed} percent values")
    return table


def _opposition_poll_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Return the survey table whose columns include the fewer-or-none share.

    The article also has a later seven-country table about whether immigration
    over the past ten years was too high. That is a different question, so the
    selector keeps the table that names a fewer-or-none column.
    """
    ranked = []
    for index, table in enumerate(tables):
        columns = _opposition_columns(table)
        if columns is None:
            continue
        parsed = sum(_percent(value) is not None for value in table[columns[1]])
        if parsed < 10:
            continue
        ranked.append((parsed, index, table))
    if not ranked:
        raise ValueError("Wikipedia page has no opposition-to-immigration poll table")
    parsed, index, table = max(ranked, key=lambda item: item[0])
    _log(f"wikipedia: opposition table {index} has {parsed} percent values")
    return table


def _opposition_columns(table: pd.DataFrame) -> tuple[object, object] | None:
    country = _find_column(table, lambda label: label.startswith("country"))
    fewer = _find_column(table, lambda label: "fewer" in label and "%" in label)
    if country is None or fewer is None:
        return None
    return country, fewer


def _survey_year(html: str, fallback_year: int) -> int:
    """Year of the cross-country survey, taken from the sentence before its table."""
    match = SURVEY_INTRO.search(html)
    if match:
        return int(match.group(1))
    _log(f"wikipedia: opposition survey year not found; stored under {fallback_year}")
    return fallback_year


def _immigrant_share_table(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    """Return the destination table that reports immigrants as a population share.

    The emigrant table on the same page counts people by origin and has no
    population-share column, so column names keep the two lists apart.
    """
    ranked = []
    for index, table in enumerate(tables):
        columns = _immigrant_columns(table)
        if columns is None:
            continue
        _country, percent_column, year = columns
        parsed = sum(_percent(value) is not None for value in table[percent_column])
        if parsed < 20:
            continue
        ranked.append((parsed, index, table, year))
    if not ranked:
        raise ValueError("Wikipedia page has no immigrant population share table")
    parsed, index, table, year = max(ranked, key=lambda item: item[0])
    if year is None:
        raise ValueError("Immigrant population table has no year in its column heading")
    _log(f"wikipedia: immigrant table {index} has {parsed} percent values for {year}")
    return table, year


def _immigrant_columns(table: pd.DataFrame) -> tuple[object, object, int | None] | None:
    country = _find_column(
        table,
        lambda label: "country" in label and "origin" not in label,
    )
    percent = _find_column(
        table,
        lambda label: "percentage" in label and "total population" in label and "female" not in label,
    )
    count = _find_column(
        table,
        lambda label: "immigrant" in label and "female" not in label and "%" not in label,
    )
    if country is None or percent is None:
        return None
    year = _source_year(count if count is not None else percent)
    return country, percent, year


def _percent_columns(table: pd.DataFrame) -> tuple[object, object, object | None] | None:
    country = _find_column(table, lambda label: label == "country")
    percent = _find_column(table, lambda label: "total" in label and "%" in label)
    if country is None or percent is None:
        return None
    notes = _find_column(table, lambda label: "note" in label)
    return country, percent, notes


def _find_column(table: pd.DataFrame, matches) -> object | None:
    for column in table.columns:
        if matches(_label(column)):
            return column
    return None


def _label(column: object) -> str:
    if isinstance(column, tuple):
        text = " ".join(str(part) for part in column)
    else:
        text = str(column)
    return " ".join(text.replace("\xa0", " ").split()).casefold()


def _english_rows(
    frame: pd.DataFrame,
    codes: dict[str, str],
    fallback_year: int,
) -> list[dict]:
    """One row per mapped country with a numeric total percent."""
    country_column, percent_column, notes_column = _percent_columns(frame) or (None, None, None)
    if country_column is None or percent_column is None:
        raise ValueError("English-speaking table is missing its country or percent column")
    rows = []
    unmapped = []
    invalid = []
    fallback = []
    for record in frame.to_dict(orient="records"):
        name = _country_name(record.get(country_column))
        percent = _percent(record.get(percent_column))
        if not name:
            continue
        if percent is None:
            invalid.append(name)
            continue
        code = codes.get(name)
        if code is None:
            unmapped.append(name)
            continue
        note = "" if notes_column is None else record.get(notes_column)
        year = _source_year(note)
        if year is None:
            year = fallback_year
            fallback.append(name)
        rows.append({"country": name, "code": code, "value": percent, "year": year})
    if invalid:
        _log(f"wikipedia: skipped non-numeric percent for {', '.join(invalid)}")
    if unmapped:
        _log(f"wikipedia: skipped unmapped countries {', '.join(unmapped)}")
    if fallback:
        _log(
            f"wikipedia: {len(fallback)} countries have no source year; "
            f"stored under {fallback_year}"
        )
    return rows


def _fixed_year_rows(
    frame: pd.DataFrame,
    codes: dict[str, str],
    columns,
    year: int,
    label: str,
) -> list[dict]:
    """One row per mapped country. Every value shares the table's year."""
    found = columns(frame)
    if found is None:
        raise ValueError(f"Wikipedia {label} table is missing its country or percent column")
    country_column, value_column = found[0], found[1]
    rows = []
    unmapped = []
    invalid = []
    for record in frame.to_dict(orient="records"):
        name = _country_name(record.get(country_column))
        value = _percent(record.get(value_column))
        if not name:
            continue
        if value is None:
            invalid.append(name)
            continue
        code = codes.get(name)
        if code is None:
            unmapped.append(name)
            continue
        rows.append({"country": name, "code": code, "value": value, "year": year})
    if invalid:
        _log(f"wikipedia: skipped non-numeric percent for {', '.join(invalid)}")
    if unmapped:
        _log(f"wikipedia: skipped unmapped countries {', '.join(unmapped)}")
    return rows


def _country_name(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return FOOTNOTE.sub("", str(value)).strip()


def _percent(value: object) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = FOOTNOTE.sub("", str(value)).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    number = _json_number(text)
    if number is None or number < 0 or number > 100:
        return None
    return number


def _source_year(note: object) -> int | None:
    if note is None or (isinstance(note, float) and math.isnan(note)):
        return None
    years = [int(match) for match in YEAR.findall(str(note))]
    return max(years) if years else None


def _series(rows: list[dict]) -> list[dict]:
    by_year: dict[int, list[dict]] = {}
    for row in rows:
        by_year.setdefault(row["year"], []).append(
            {"country": row["country"], "code": row["code"], "value": row["value"]}
        )
    series = []
    for year in sorted(by_year):
        data = sorted(by_year[year], key=lambda item: (item["country"].casefold(), item["code"]))
        series.append({"year": year, "count": len(data), "data": data})
    return series


def _country_codes() -> dict[str, str]:
    """Map display names, including Wikipedia aliases, to ISO alpha-3 codes."""
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


def _download(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


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


def _json_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, 4)


def main() -> None:
    WikipediaImporter().run()


if __name__ == "__main__":
    main()
