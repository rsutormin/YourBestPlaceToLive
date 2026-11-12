import pandas as pd
import pytest

from importers.oecd_importer import (
    OecdImporter,
    _indicator,
    _json_number,
    _pisa_frame,
    _values,
    _year,
)


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        OecdImporter(start_year=2021, end_year=2020)


def test_values_skip_aggregates_and_keep_country_years():
    frame = pd.DataFrame(
        {
            "REF_AREA": ["USA", "USA", "OECD", "EU27", "US", "FRA"],
            "Reference area": ["United States", "United States", "OECD", "European Union", "United States", "France"],
            "TIME_PERIOD": ["2020", "2021-Q4", "2021", "2021", "2021", "2019"],
            "OBS_VALUE": [10, "12.5", 99, 99, 5, 7],
        }
    )

    values = _values(frame, 2020, 2021)

    assert values == {
        2020: {"USA": ("United States", 10)},
        2021: {"USA": ("United States", 12.5)},
    }


def test_pisa_frame_keeps_country_mean_scores():
    frame = pd.DataFrame(
        [
            ["", "", ""],
            ["", "PISA 2018", "PISA 2022"],
            ["Country", "Mean score", "Mean score"],
            ["Finland*", 500.12346, 490],
            ["B-S-J-Z (China)", 555, 560],
            ["Kosovo", None, "m"],
        ]
    )

    records = _pisa_frame(frame).to_dict(orient="records")

    assert records == [
        {"REF_AREA": "FIN", "country": "Finland", "TIME_PERIOD": 2018, "OBS_VALUE": 500.1235},
        {"REF_AREA": "FIN", "country": "Finland", "TIME_PERIOD": 2022, "OBS_VALUE": 490},
    ]


def test_percentage_metric_divides_matching_country_years(monkeypatch):
    importer = OecdImporter(start_year=2020, end_year=2021, include_series=True)
    frames = {
        "overtime_workers": _oecd_frame(
            [("USA", "United States", 2020, 25), ("USA", "United States", 2021, 10), ("FRA", "France", 2021, 5), ("NAM", "Namibia", 2021, 8)]
        ),
        "total_workers": _oecd_frame(
            [("USA", "United States", 2020, 200), ("USA", "United States", 2021, 0), ("FRA", "France", 2021, 100)]
        ),
    }
    monkeypatch.setattr(importer, "fetch_frame", lambda indicator: frames[indicator["key"]])

    documents = dict(importer.to_documents(keys=["overtime_workers_percentage", "overtime_workers", "total_workers"]))
    percentage = documents["overtime_workers_percentage"]

    assert set(documents) == {"overtime_workers_percentage"}
    assert percentage["metadata"]["scope"] == "World"
    assert percentage["metadata"]["reversedScale"] is True
    assert percentage["metadata"]["importance"] == 0.5
    assert percentage["metadata"]["units"] == "percent"
    assert percentage["data"] == [
        {"country": "France", "code": "FRA", "value": 5.0, "year": 2021},
        {"country": "United States", "code": "USA", "value": 12.5, "year": 2020},
    ]
    counts = {entry["year"]: entry["count"] for entry in percentage["series"]}
    assert counts == {2020: 1, 2021: 1}


def test_indicator_lookup():
    assert _indicator("tax_wedge")["reversed_scale"] is True
    with pytest.raises(KeyError):
        _indicator("missing")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2021-Q3", 2021),
        ("2020", 2020),
        ("20", None),
        (None, None),
        ("abc", None),
    ],
)
def test_year(value, expected):
    assert _year(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (":", None),
        ("m", None),
        ("", None),
        (" 12.5 ", 12.5),
        (float("nan"), None),
    ],
)
def test_json_number(value, expected):
    assert _json_number(value) == expected


def _oecd_frame(rows: list[tuple[str, str, int, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "REF_AREA": [code for code, _name, _year, _value in rows],
            "Reference area": [name for _code, name, _year, _value in rows],
            "TIME_PERIOD": [year for _code, _name, year, _value in rows],
            "OBS_VALUE": [value for _code, _name, _year, value in rows],
        }
    )
