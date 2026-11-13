# Copyright (c) 2026 Roman Sutormin. MIT License.

import json
import math
from datetime import datetime, timezone

import pandas as pd
import pytest
import requests

from importers import world_bank_importer
from importers.world_bank_importer import (
    PAGE_ATTEMPTS,
    PAGE_SIZE,
    PAGE_TIMEOUT_SECONDS,
    _retry_wait_seconds,
    WorldBankImporter,
    _as_year,
    _indicator_page,
    _cost_burden,
    _countries_with_value,
    _json_number,
    _latest_country_rows,
    _lookup,
    _series_codes,
    _series_frame,
    main,
)


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        WorldBankImporter(start_year=2021, end_year=2020)


def test_defaults_cover_the_requested_years():
    importer = WorldBankImporter(start_year=2020, end_year=2022)
    assert list(importer.years) == [2020, 2021, 2022]
    assert importer.output_dir.name == "data"


def test_default_bulk_range_starts_in_2020_and_includes_the_current_year():
    importer = WorldBankImporter()
    current_year = datetime.now(timezone.utc).year

    assert importer.start_year == 2020
    assert importer.end_year == current_year
    assert list(importer.years)[0] == 2020
    assert list(importer.years)[-1] == current_year


def test_cost_burden_range_is_the_two_years_before_the_current_year():
    importer = WorldBankImporter()
    current_year = datetime.now(timezone.utc).year

    assert importer.cost_start_year == current_year - 2
    assert importer.cost_end_year == current_year - 1
    assert list(importer.cost_years) == [current_year - 2, current_year - 1]


def test_lookup_reads_country_labels_and_rounds_values():
    frame = pd.DataFrame(
        {
            "Country": ["United States", "France"],
            "Series": [
                "GDP per capita, PPP (current international $)",
                "GDP per capita, PPP (current international $)",
            ],
            2020: [100.12341, None],
            "YR2021": [110.5, math.nan],
        },
        index=pd.MultiIndex.from_tuples(
            [
                ("USA", "NY.GDP.PCAP.PP.CD"),
                ("FRA", "NY.GDP.PCAP.PP.CD"),
            ],
            names=["economy", "series"],
        ),
    )

    values, country_names, series_names = _lookup(frame)

    assert country_names == {"USA": "United States", "FRA": "France"}
    assert series_names["NY.GDP.PCAP.PP.CD"].startswith("GDP")
    assert values[("USA", "NY.GDP.PCAP.PP.CD", 2020)] == 100.1234
    assert values[("USA", "NY.GDP.PCAP.PP.CD", 2021)] == 110.5
    assert values[("FRA", "NY.GDP.PCAP.PP.CD", 2020)] is None
    assert values[("FRA", "NY.GDP.PCAP.PP.CD", 2021)] is None


def test_lookup_rejects_a_frame_without_economy_and_series():
    with pytest.raises(ValueError, match="columns"):
        _lookup(pd.DataFrame({"value": [1]}))


def test_countries_with_value_drop_missing_numbers_and_sort_by_name():
    values = {
        ("USA", "NY.GDP.PCAP.PP.CD", 2021): 1.0,
        ("FRA", "NY.GDP.PCAP.PP.CD", 2021): None,
        ("DEU", "NY.GDP.PCAP.PP.CD", 2021): 2.0,
        ("DEU", "FP.CPI.TOTL.ZG", 2021): 3.0,
    }
    names = {"USA": "United States", "FRA": "France", "DEU": "Germany"}

    assert _countries_with_value(values, names, "NY.GDP.PCAP.PP.CD", 2021) == ["DEU", "USA"]


def test_latest_country_rows_keep_the_newest_year():
    series = [
        {"year": 2020, "count": 1, "data": [{"country": "France", "code": "FRA", "value": 1}]},
        {"year": 2021, "count": 2, "data": [
            {"country": "United States", "code": "USA", "value": 3},
            {"country": "France", "code": "FRA", "value": 2},
        ]},
    ]

    assert _latest_country_rows(series) == [
        {"country": "France", "code": "FRA", "value": 2, "year": 2021},
        {"country": "United States", "code": "USA", "value": 3, "year": 2021},
    ]


def test_to_documents_uses_indicator_names_and_latest_values():
    importer = WorldBankImporter(start_year=2020, end_year=2021, include_series=True)
    documents = dict(importer.to_documents(_gdp_and_inflation_frame()))
    gdp = documents["gdp_per_capita_ppp"]
    inflation = documents["inflation_rate"]

    assert gdp["metadata"]["description"] == "GDP per capita, PPP"
    assert "(" not in gdp["metadata"]["description"]
    assert gdp["metadata"]["scope"] == "World"
    assert gdp["metadata"]["reversedScale"] is False
    assert gdp["metadata"]["importance"] == 0.75
    assert gdp["metadata"]["dataSize"] == 2
    assert inflation["metadata"]["reversedScale"] is True
    assert gdp["data"] == [
        {"country": "France", "code": "FRA", "value": 90, "year": 2021},
        {"country": "United States", "code": "USA", "value": 110.5, "year": 2021},
    ]
    assert inflation["data"] == [
        {"country": "United States", "code": "USA", "value": 1.5, "year": 2020},
    ]
    counts = {entry["year"]: entry["count"] for entry in gdp["series"]}
    assert counts == {2020: 1, 2021: 2}
    assert "series" not in WorldBankImporter(start_year=2020, end_year=2021).to_documents(
        _gdp_and_inflation_frame()
    )[0][1]


def test_regular_series_load_together_for_the_full_year_range(monkeypatch):
    captured = {}

    def data_frame(series, economy, time, labels, numericTimeKeys, skipAggs):
        captured["series"] = list(series)
        captured["economy"] = economy
        captured["time"] = list(time)
        captured["labels"] = labels
        captured["numericTimeKeys"] = numericTimeKeys
        captured["skipAggs"] = skipAggs
        return _gdp_and_inflation_frame()

    def indicator_page(*_args, **_kwargs):
        raise AssertionError("regular series must not use the paged API")

    monkeypatch.setattr("importers.world_bank_importer.wb.data.DataFrame", data_frame)
    monkeypatch.setattr("importers.world_bank_importer._indicator_page", indicator_page)

    frame = WorldBankImporter(
        start_year=2020,
        end_year=2022,
        keys=["gdp_per_capita_ppp", "inflation_rate"],
    ).fetch()

    assert captured["series"] == ["NY.GDP.PCAP.PP.CD", "FP.CPI.TOTL.ZG"]
    assert captured["economy"] == "all"
    assert captured["time"] == [2020, 2021, 2022]
    assert captured["labels"] is True
    assert captured["numericTimeKeys"] is True
    assert captured["skipAggs"] is True
    assert ("FRA", "NY.GDP.PCAP.PP.CD") in frame.index


def test_fetch_pages_only_the_cost_burden_inputs(tmp_path, capsys, monkeypatch):
    economies = pd.DataFrame({"name": ["France"]}, index=pd.Index(["FRA"], name="id"))
    requested = []
    importer = WorldBankImporter(output_dir=tmp_path, keys=["cost_burden_index"])
    years = list(importer.cost_years)

    def economy_frame(skipAggs=False):
        assert skipAggs is True
        return economies

    def indicator_page(code, year, page):
        requested.append((code, year, page))
        pages = 2
        row = {
            "indicator": {"id": code, "value": code},
            "country": {"id": "FR", "value": "France"},
            "countryiso3code": "FRA",
            "date": str(year),
            "value": 1.0 if page == 1 else 2.0,
        }
        aggregate = {
            "indicator": {"id": code, "value": code},
            "country": {"id": "1W", "value": "World"},
            "countryiso3code": "WLD",
            "date": str(year),
            "value": 9.0,
        }
        rows = [row, aggregate] if page == 1 else []
        return {"page": page, "pages": pages}, rows

    def data_frame(*_args, **_kwargs):
        raise AssertionError("cost burden must not use the bulk request")

    monkeypatch.setattr("importers.world_bank_importer.wb.economy.DataFrame", economy_frame)
    monkeypatch.setattr("importers.world_bank_importer.wb.data.DataFrame", data_frame)
    monkeypatch.setattr("importers.world_bank_importer._indicator_page", indicator_page)

    frame = importer.fetch()
    output = capsys.readouterr().out
    codes = ["PA.NUS.GDP.PLI", "NY.GDP.PCAP.CD"]

    assert requested == [(code, year, page) for code in codes for year in years for page in (1, 2)]
    assert ("FRA", "PA.NUS.GDP.PLI") in frame.index
    assert ("WLD", "PA.NUS.GDP.PLI") not in frame.index
    assert frame.loc[("FRA", "PA.NUS.GDP.PLI"), years[0]] == 1.0
    assert "world-bank countries: 1" in output
    assert f"world-bank 1/{len(codes)} PA.NUS.GDP.PLI: fetching {years[0]} page 1" in output
    assert f"world-bank 1/{len(codes)} PA.NUS.GDP.PLI: {years[0]} page 1/2 (25%)" in output
    assert f"world-bank 1/{len(codes)} PA.NUS.GDP.PLI: {years[-1]} page 2/2 (100%)" in output
    assert "rows in" in output


def test_indicator_page_retries_a_timeout(capsys, monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [{"page": 1, "pages": 1}, []]

    def fake_get(url, params, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise requests.ReadTimeout("timed out")
        return Response()

    waits = []
    monkeypatch.setattr(world_bank_importer.requests, "get", fake_get)
    monkeypatch.setattr(world_bank_importer.time, "sleep", waits.append)

    header, rows = _indicator_page("PA.NUS.GDP.PLI", 2020, 3)
    output = capsys.readouterr().out

    assert header["pages"] == 1
    assert rows == []
    assert calls == [PAGE_TIMEOUT_SECONDS, PAGE_TIMEOUT_SECONDS]
    assert PAGE_TIMEOUT_SECONDS == 30
    assert waits == [_retry_wait_seconds(1)]
    assert (
        f"PA.NUS.GDP.PLI 2020 page 3: attempt 1/{PAGE_ATTEMPTS} failed, "
        f"waiting {_retry_wait_seconds(1)}s"
    ) in output


def test_retry_wait_doubles_after_each_failure():
    assert [_retry_wait_seconds(attempt) for attempt in (1, 2, 3, 4)] == [15, 30, 60, 120]


def test_indicator_page_stops_after_the_last_attempt(monkeypatch):
    def fake_get(url, params, timeout):
        raise requests.ReadTimeout("timed out")

    monkeypatch.setattr(world_bank_importer.requests, "get", fake_get)
    monkeypatch.setattr(world_bank_importer.time, "sleep", lambda seconds: None)

    with pytest.raises(requests.ReadTimeout):
        _indicator_page("PA.NUS.GDP.PLI", 2020, 3)


def test_debug_prints_each_fetched_cost_burden_url(tmp_path, capsys, monkeypatch):
    economies = pd.DataFrame({"name": ["France"]}, index=pd.Index(["FRA"], name="id"))
    importer = WorldBankImporter(output_dir=tmp_path, keys=["cost_burden_index"], debug=True)

    def economy_frame(skipAggs=False):
        world_bank_importer.requests.get("https://api.worldbank.org/v2/country?per_page=1000")
        return economies

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [{"page": 1, "pages": 1}, []]

    monkeypatch.setattr("importers.world_bank_importer.wb.economy.DataFrame", economy_frame)
    monkeypatch.setattr("importers.world_bank_importer.requests.get", lambda *args, **kwargs: Response())

    importer.fetch()
    output = capsys.readouterr().out

    assert "world-bank GET https://api.worldbank.org/v2/country?per_page=1000" in output
    assert "indicator/PA.NUS.GDP.PLI?" in output
    assert "indicator/NY.GDP.PCAP.CD?" in output
    assert f"per_page={PAGE_SIZE}" in output
    assert "page=1" in output
    for year in importer.cost_years:
        assert f"date={year}" in output

    capsys.readouterr()
    WorldBankImporter(output_dir=tmp_path, keys=["cost_burden_index"]).fetch()
    assert "world-bank GET" not in capsys.readouterr().out


def test_fetch_reports_cost_burden_progress_across_its_two_years(tmp_path, capsys, monkeypatch):
    economies = pd.DataFrame({"name": ["France"]}, index=pd.Index(["FRA"], name="id"))
    importer = WorldBankImporter(output_dir=tmp_path, keys=["cost_burden_index"])
    years = list(importer.cost_years)

    def economy_frame(skipAggs=False):
        return economies

    def indicator_page(code, year, page):
        assert page == 1
        return {"page": 1, "pages": 1}, [
            {
                "indicator": {"id": code, "value": code},
                "country": {"id": "FR", "value": "France"},
                "countryiso3code": "FRA",
                "date": str(year),
                "value": float(year),
            }
        ]

    monkeypatch.setattr("importers.world_bank_importer.wb.economy.DataFrame", economy_frame)
    monkeypatch.setattr("importers.world_bank_importer._indicator_page", indicator_page)

    importer.fetch()
    output = capsys.readouterr().out

    assert f"PA.NUS.GDP.PLI: {years[0]} page 1/1 (50%)" in output
    assert f"PA.NUS.GDP.PLI: {years[1]} page 1/1 (100%)" in output


def test_stored_cost_burden_pages_are_reused_and_removed_after_export(tmp_path, capsys, monkeypatch):
    economies = pd.DataFrame({"name": ["France"]}, index=pd.Index(["FRA"], name="id"))
    calls = []

    def economy_frame(skipAggs=False):
        return economies

    def indicator_page(code, year, page):
        calls.append((code, year, page))
        return {"page": 1, "pages": 1}, [
            {
                "indicator": {"id": code, "value": code},
                "country": {"id": "FR", "value": "France"},
                "countryiso3code": "FRA",
                "date": str(year),
                "value": 1.5,
            }
        ]

    monkeypatch.setattr("importers.world_bank_importer.wb.economy.DataFrame", economy_frame)
    monkeypatch.setattr("importers.world_bank_importer._indicator_page", indicator_page)
    importer = WorldBankImporter(output_dir=tmp_path, keys=["cost_burden_index"])
    year = importer.cost_start_year
    cache = tmp_path / ".world-bank-pages"
    stored = cache / f"PA.NUS.GDP.PLI-{year}-1.json"
    other = cache / "IT.NET.USER.ZS-2020-1.json"
    first_page = ("PA.NUS.GDP.PLI", year, 1)

    importer.fetch()
    assert stored.is_file()
    assert first_page in calls
    downloaded = len(calls)

    stored.write_text("{", encoding="utf-8")
    importer.fetch()
    assert calls.count(first_page) == 2
    assert json.loads(stored.read_text(encoding="utf-8"))[0]["pages"] == 1

    importer.fetch()
    output = capsys.readouterr().out
    assert calls.count(first_page) == 2
    assert len(calls) == downloaded + 1
    assert f"PA.NUS.GDP.PLI: {year} page 1 stored" in output

    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("[]", encoding="utf-8")
    paths = importer.run()

    assert paths[0].name == "cost_burden_index.json"
    assert not stored.exists()
    assert other.is_file()
    assert "world-bank removed" in capsys.readouterr().out


def test_series_frame_places_values_on_year_columns():
    frame = _series_frame(
        "NY.GDP.PCAP.CD",
        [
            _observation("FRA", "France", "2021", 10),
            _observation("USA", "United States", "2020", 20),
        ],
        range(2020, 2022),
    )

    assert frame.loc[("FRA", "NY.GDP.PCAP.CD"), "Country"] == "France"
    assert pd.isna(frame.loc[("FRA", "NY.GDP.PCAP.CD"), 2020])
    assert frame.loc[("USA", "NY.GDP.PCAP.CD"), 2020] == 20
    assert frame.loc[("FRA", "NY.GDP.PCAP.CD"), 2021] == 10


def _observation(code: str, name: str, year: str, value: float) -> dict:
    return {
        "indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita (current US$)"},
        "country": {"id": code[:2], "value": name},
        "countryiso3code": code,
        "date": year,
        "value": value,
    }


def test_series_codes_include_the_cost_burden_inputs():
    codes = _series_codes()

    assert "PA.NUS.GDP.PLI" in codes
    assert "NY.GDP.PCAP.CD" in codes
    assert "PA.NUS.GDP.PLI / NY.GDP.PCAP.CD" not in codes


def test_keys_limit_downloads_and_documents():
    assert _series_codes(["cost_burden_index"]) == ["PA.NUS.GDP.PLI", "NY.GDP.PCAP.CD"]
    importer = WorldBankImporter(start_year=2020, end_year=2021, keys=["inflation_rate"])
    documents = importer.to_documents(_gdp_and_inflation_frame())

    assert [key for key, _document in documents] == ["inflation_rate"]


def test_unknown_metric_key_is_rejected():
    with pytest.raises(ValueError, match="not_a_metric"):
        WorldBankImporter(keys=["not_a_metric"])


def test_main_forwards_metric_keys(monkeypatch):
    constructed = {}

    class Stop(Exception):
        pass

    class FakeImporter:
        def __init__(self, keys=None, debug=False):
            constructed["keys"] = keys
            constructed["debug"] = debug

        def run(self):
            raise Stop()

    monkeypatch.setattr("importers.world_bank_importer.WorldBankImporter", FakeImporter)

    with pytest.raises(Stop):
        main(["--keys", "inflation_rate", "homicide_rate"])
    assert constructed["keys"] == ["inflation_rate", "homicide_rate"]
    assert constructed["debug"] is False

    with pytest.raises(Stop):
        main([])
    assert constructed["keys"] is None
    assert constructed["debug"] is False

    with pytest.raises(Stop):
        main(["--debug", "--keys", "inflation_rate"])
    assert constructed["debug"] is True


@pytest.mark.parametrize(
    ("price_level", "gdp_per_capita", "expected"),
    [
        (0.8, 40000, 0.02),
        (2, 10000, 0.2),
        (None, 40000, None),
        (0.8, None, None),
        (0.8, 0, None),
        (0.8, -0.0, None),
        (float("nan"), 40000, None),
        (0.8, float("nan"), None),
        (float("inf"), 40000, None),
        (1, float("inf"), None),
    ],
)
def test_cost_burden_skips_missing_values_and_zero_gdp(price_level, gdp_per_capita, expected):
    assert _cost_burden(price_level, gdp_per_capita) == expected


def test_cost_burden_index_uses_the_latest_year_both_inputs_exist():
    importer = WorldBankImporter()
    earlier, later = importer.cost_start_year, importer.cost_end_year
    documents = dict(importer.to_documents(_cost_burden_frame(earlier, later)))
    metric = documents["cost_burden_index"]

    assert metric["metadata"]["description"] == "Relative cost-of-living burden"
    assert "(" not in metric["metadata"]["description"]
    assert metric["metadata"]["reversedScale"] is True
    assert metric["metadata"]["importance"] == 1.0
    assert metric["metadata"]["units"] == "per $1,000 of GDP per capita"
    assert metric["metadata"]["code"] == "PA.NUS.GDP.PLI / NY.GDP.PCAP.CD"
    assert metric["data"] == [
        {"country": "Canada", "code": "CAN", "value": 0.2, "year": earlier},
        {"country": "United States", "code": "USA", "value": 0.02, "year": later},
    ]


def test_save_writes_one_json_file_per_metric(tmp_path):
    importer = WorldBankImporter(start_year=2020, end_year=2020, output_dir=tmp_path)
    documents = importer.to_documents(_gdp_and_inflation_frame())

    paths = importer.save(documents)

    saved = json.loads((tmp_path / "gdp_per_capita_ppp.json").read_text(encoding="utf-8"))
    assert saved["metadata"]["key"] == "gdp_per_capita_ppp"
    assert paths[0].name == "gdp_per_capita_ppp.json"


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("YR2020", 2020),
        ("2021", 2021),
        (2022, 2022),
        (2022.0, 2022),
        ("Country", None),
        (True, None),
        (1899, None),
        (2101, None),
    ],
)
def test_as_year(column, expected):
    assert _as_year(column) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (1.23456, 1.2346),
        ("4.5", 4.5),
    ],
)
def test_json_number(value, expected):
    assert _json_number(value) == expected


def _cost_burden_frame(earlier: int = 2020, later: int = 2021) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Country": [
                "United States",
                "France",
                "Germany",
                "Japan",
                "Canada",
                "United States",
                "France",
                "Germany",
                "Japan",
                "Canada",
            ],
            "Series": ["Price level ratio"] * 5 + ["GDP per capita (current US$)"] * 5,
            earlier: [80, 120, None, 100, 200, 40000, 0, 50000, None, 10000],
            later: [90, None, 110, 100, None, 45000, 30000, math.nan, 0, None],
        },
        index=pd.MultiIndex.from_tuples(
            [
                ("USA", "PA.NUS.GDP.PLI"),
                ("FRA", "PA.NUS.GDP.PLI"),
                ("DEU", "PA.NUS.GDP.PLI"),
                ("JPN", "PA.NUS.GDP.PLI"),
                ("CAN", "PA.NUS.GDP.PLI"),
                ("USA", "NY.GDP.PCAP.CD"),
                ("FRA", "NY.GDP.PCAP.CD"),
                ("DEU", "NY.GDP.PCAP.CD"),
                ("JPN", "NY.GDP.PCAP.CD"),
                ("CAN", "NY.GDP.PCAP.CD"),
            ],
            names=["economy", "series"],
        ),
    )


def _gdp_and_inflation_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Country": ["United States", "France", "United States"],
            "Series": [
                "GDP per capita, PPP (current international $)",
                "GDP per capita, PPP (current international $)",
                "Inflation, consumer prices (annual %)",
            ],
            2020: [100.12341, None, 1.5],
            2021: [110.5, 90, None],
        },
        index=pd.MultiIndex.from_tuples(
            [
                ("USA", "NY.GDP.PCAP.PP.CD"),
                ("FRA", "NY.GDP.PCAP.PP.CD"),
                ("USA", "FP.CPI.TOTL.ZG"),
            ],
            names=["economy", "series"],
        ),
    )
