# Copyright (c) 2026 Roman Sutormin. MIT License.

import math

import pandas as pd
import pytest

from importers import owid_importer
from importers.owid_importer import OwidImporter, _add_code, _alias_labels, _as_year, _json_number, _values


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        OwidImporter(start_year=2021, end_year=2020)


def test_values_use_iso_codes_and_skip_regions():
    frame = pd.DataFrame(
        {
            "country": ["United States", "World", "France", "France"],
            "year": [2021, 2021, 2019, 2020],
            "iso_code": ["USA", "OWID_WRL", "FRA", "FRA"],
            "co2_per_capita": [14.12346, 4, 9, 4.5],
        }
    )
    indicator = {"column": "co2_per_capita", "code_column": "iso_code"}

    assert _values(frame, indicator, {}) == {
        2019: {"FRA": ("France", 9)},
        2020: {"FRA": ("France", 4.5)},
        2021: {"USA": ("United States", 14.1235)},
    }


def test_values_resolve_country_names_when_no_code_column_is_present():
    frame = pd.DataFrame(
        {
            "country": ["United States", "Atlantis"],
            "year": [2020, 2020],
            "life_expectancy_0": [77.1, 80],
        }
    )

    values = _values(frame, {"column": "life_expectancy_0"}, {"United States": "USA"})

    assert values == {2020: {"USA": ("United States", 77.1)}}


def test_to_documents_builds_world_metrics_without_calling_the_catalog(monkeypatch):
    importer = OwidImporter(start_year=2020, end_year=2021)
    monkeypatch.setattr(owid_importer, "_country_codes", lambda: {"United States": "USA"})
    monkeypatch.setattr(importer, "fetch_table", _fetch_table)

    documents = dict(importer.to_documents())
    emissions = documents["co2_emissions_per_capita"]
    expectancy = documents["life_expectancy"]

    assert emissions["metadata"]["scope"] == "World"
    assert emissions["metadata"]["description"] == "Annual CO₂ emissions, per capita"
    assert emissions["metadata"]["reversedScale"] is True
    assert emissions["metadata"]["importance"] == 0.25
    assert emissions["data"] == [
        {"country": "France", "code": "FRA", "value": 4.5, "year": 2020},
        {"country": "United States", "code": "USA", "value": 14.1235, "year": 2021},
    ]
    assert expectancy["metadata"]["reversedScale"] is False
    assert expectancy["data"] == [
        {"country": "United States", "code": "USA", "value": 77.1, "year": 2020},
    ]
    assert documents["pm25_exposure"]["data"] == []


def test_alias_labels_parse_lists_and_plain_names():
    assert _alias_labels(None) == []
    assert _alias_labels(float("nan")) == []
    assert _alias_labels("") == []
    assert _alias_labels("France") == ["France"]
    assert _alias_labels('["USA", "", "United States"]') == ["USA", "United States"]
    assert _alias_labels("[not json") == ["[not json"]


def test_add_code_keeps_the_first_name():
    codes: dict[str, str] = {}
    _add_code(codes, " France ", "FRA")
    _add_code(codes, "France", "XXX")
    _add_code(codes, None, "USA")
    _add_code(codes, " ", "USA")
    assert codes == {"France": "FRA"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2020, 2020),
        (2020.0, 2020),
        ("2021", 2021),
        (True, None),
        (None, None),
        (float("nan"), None),
        (1899, None),
    ],
)
def test_as_year(value, expected):
    assert _as_year(value) == expected


def test_json_number_drops_non_finite_values():
    assert _json_number(math.inf) is None
    assert _json_number(1.23456) == 1.2346


def _fetch_table(indicator: dict) -> pd.DataFrame:
    column = indicator["column"]
    if indicator["key"] == "co2_emissions_per_capita":
        return pd.DataFrame(
            {
                "country": ["United States", "World", "France", "France"],
                "year": [2021, 2021, 2019, 2020],
                "iso_code": ["USA", "OWID_WRL", "FRA", "FRA"],
                column: [14.12346, 4, 9, 4.5],
            }
        )
    if indicator["key"] == "life_expectancy":
        return pd.DataFrame(
            {
                "country": ["United States", "Atlantis"],
                "year": [2020, 2020],
                column: [77.1, 80],
            }
        )
    return pd.DataFrame(columns=["country", "year", column])
