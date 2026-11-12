import pandas as pd
import pytest

from importers.heritage_importer import HeritageImporter, _country_codes, _score_rows


def _sheet(*rows: list) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        HeritageImporter(start_year=2025, end_year=2024)


def test_score_rows_keep_business_freedom_when_the_overall_score_is_missing():
    frame = _sheet(
        [None, "COMPONENT SCORES"],
        ["Country", "Year", "Overall Score", "Business Freedom"],
        ["United States", 2024, 70.2, 84.1],
        ["France", 2024, "N/A", 80],
        ["Nowhere", 2024, 50, 40],
    )

    rows, unmapped = _score_rows(frame, 2024, {"United States": "USA", "France": "FRA"})

    assert unmapped == ["Nowhere"]
    assert rows == [
        {"country": "United States", "code": "USA", "year": 2024, "overall": 70.2, "business": 84.1},
        {"country": "France", "code": "FRA", "year": 2024, "overall": None, "business": 80.0},
    ]


def test_score_rows_use_the_edition_year_when_the_sheet_has_no_year_column():
    frame = _sheet(
        ["Country", "Overall Score", "Judicial Efectiveness", "Business Freedom", "Monitary Freedom"],
        ["Côte d’Ivoire", 45.8, 30, 59.3, 74.7],
        ["Burma", 101, 4, 37.9, 57.5],
    )

    rows, unmapped = _score_rows(frame, 2026, {"Côte d'Ivoire": "CIV", "Burma": "MMR"})

    assert unmapped == []
    assert rows == [
        {"country": "Côte d’Ivoire", "code": "CIV", "year": 2026, "overall": 45.8, "business": 59.3},
        {"country": "Burma", "code": "MMR", "year": 2026, "overall": None, "business": 37.9},
    ]


def test_to_documents_keeps_the_newest_score_for_each_metric():
    older = _sheet(
        ["Country", "Overall Score", "Business Freedom"],
        ["France", 50, 60],
        ["United States", 70, None],
    )
    newer = _sheet(
        ["Country", "Overall Score", "Business Freedom"],
        ["France", 68, "N/A"],
        ["Afghanistan", "N/A", 33.7],
    )
    documents = dict(
        HeritageImporter(start_year=2025, end_year=2026, include_series=True).to_documents(
            {2025: older, 2026: newer}
        )
    )
    overall = documents["economic_freedom"]
    business = documents["business_freedom"]

    assert overall["metadata"]["description"] == "Economic freedom score"
    assert "(" not in overall["metadata"]["description"]
    assert overall["metadata"]["source"] == "Heritage Foundation"
    assert overall["metadata"]["code"] == "overall_score"
    assert overall["metadata"]["units"] == "0-100"
    assert overall["metadata"]["reversedScale"] is False
    assert overall["metadata"]["importance"] == 0.75
    assert overall["data"] == [
        {"country": "France", "code": "FRA", "value": 68.0, "year": 2026},
        {"country": "United States", "code": "USA", "value": 70.0, "year": 2025},
    ]
    assert business["metadata"]["code"] == "hf_business"
    assert business["metadata"]["description"] == "Business freedom"
    assert business["data"] == [
        {"country": "Afghanistan", "code": "AFG", "value": 33.7, "year": 2026},
        {"country": "France", "code": "FRA", "value": 60.0, "year": 2025},
    ]
    assert [entry["year"] for entry in overall["series"]] == [2025, 2026]


def test_empty_workbook_set_is_rejected():
    with pytest.raises(ValueError, match="workbooks"):
        HeritageImporter(start_year=2020, end_year=2020).to_documents({})


def test_workbook_without_the_score_columns_is_rejected():
    with pytest.raises(ValueError, match="business freedom"):
        _score_rows(pd.DataFrame([["Country", "Region"]]), 2026, {})


def test_map_names_include_heritage_aliases():
    codes = _country_codes()

    assert codes["United States"] == "USA"
    assert codes["France"] == "FRA"
    assert codes["Burma"] == "MMR"
    assert codes["The Bahamas"] == "BHS"
    assert codes["Czech Republic"] == "CZE"
