import json
import math

import pandas as pd
import pytest

from importers.world_bank_importer import (
    WorldBankImporter,
    _as_year,
    _countries_with_value,
    _json_number,
    _latest_country_rows,
    _lookup,
)


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        WorldBankImporter(start_year=2021, end_year=2020)


def test_defaults_cover_the_requested_years():
    importer = WorldBankImporter(start_year=2020, end_year=2022)
    assert list(importer.years) == [2020, 2021, 2022]
    assert importer.output_dir.name == "data"


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
