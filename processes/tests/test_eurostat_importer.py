import pandas as pd
import pytest

from importers.eurostat_importer import EurostatImporter, _json_number, _values


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        EurostatImporter(start_year=2021, end_year=2020)


def test_defaults_write_europe_files():
    importer = EurostatImporter(start_year=2020, end_year=2021)
    assert importer.output_dir.parts[-2:] == ("data", "europe")


def test_values_map_countries_and_keep_the_latest_period_in_a_year():
    frame = pd.DataFrame(
        {
            "geo\\TIME_PERIOD": ["EL", "EU27_2020", "DE", "FR"],
            "2020": [100, 1, ":", None],
            "2021-S1": [110, 2, 50, 40],
            "2021-S2": [120.25, 3, None, 41],
        }
    )

    values = _values(frame, 2020, 2021)

    assert values[2020] == {"GRC": ("Greece", 100)}
    assert values[2021] == {
        "GRC": ("Greece", 120.25),
        "DEU": ("Germany", 50),
        "FRA": ("France", 41),
    }
    assert 2020 not in _values(frame, 2021, 2021)


def test_to_documents_builds_europe_metrics_from_the_fetched_frame(monkeypatch):
    importer = EurostatImporter(start_year=2020, end_year=2021, include_series=True)
    frame = pd.DataFrame(
        {
            "geo\\TIME_PERIOD": ["EL", "DE"],
            "2020": [100, 80],
            "2021": [110, 90],
        }
    )
    monkeypatch.setattr(importer, "fetch_frame", lambda indicator: frame)

    documents = dict(importer.to_documents())
    house_prices = documents["europe_house_price_index"]

    assert house_prices["metadata"]["scope"] == "Europe"
    assert house_prices["metadata"]["source"] == "Eurostat"
    assert house_prices["metadata"]["reversedScale"] is True
    assert house_prices["data"] == [
        {"country": "Germany", "code": "DEU", "value": 90, "year": 2021},
        {"country": "Greece", "code": "GRC", "value": 110, "year": 2021},
    ]
    assert [entry["count"] for entry in house_prices["series"]] == [2, 2]
    assert "europe_minimum_wage" in documents


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (":", None),
        ("", None),
        ("12.34567", 12.3457),
        (None, None),
    ],
)
def test_json_number(value, expected):
    assert _json_number(value) == expected
