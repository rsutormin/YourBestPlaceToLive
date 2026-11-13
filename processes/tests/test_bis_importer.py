# Copyright (c) 2026 Roman Sutormin. MIT License.

import pandas as pd
import pytest

from importers.bis_importer import BisImporter, _values


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        BisImporter(start_year=2021, end_year=2020)


def test_values_keep_the_latest_quarter_and_skip_aggregates():
    frame = pd.DataFrame(
        {
            "date": ["2021-09-30", "2021-01-31", "2020-12-31", "2021-06-30", "2022-03-31", "not-a-date"],
            "country_code": ["US", "US", "US", "XM", "DE", "US"],
            "price": [110.5, 90, 80, 999, 70, 1],
        }
    )

    values = _values(frame, 2020, 2021)

    assert values == {
        2020: {"USA": ("United States", 80)},
        2021: {"USA": ("United States", 110.5)},
    }


def test_to_documents_builds_the_real_house_price_index(monkeypatch):
    importer = BisImporter(start_year=2020, end_year=2021)
    frame = pd.DataFrame(
        {
            "date": ["2021-03-31", "2021-12-31", "2020-06-30"],
            "country_code": ["DE", "US", "US"],
            "price": [70, 110.5, 80],
        }
    )
    monkeypatch.setattr(importer, "fetch_frame", lambda indicator: frame)

    documents = importer.to_documents()

    assert [key for key, _document in documents] == ["real_house_price_index"]
    document = documents[0][1]
    assert document["metadata"]["scope"] == "World"
    assert document["metadata"]["reversedScale"] is True
    assert document["metadata"]["importance"] == 0.75
    assert document["metadata"]["units"] == "index, 2010=100"
    assert "series" not in document
    assert document["data"] == [
        {"country": "Germany", "code": "DEU", "value": 70, "year": 2021},
        {"country": "United States", "code": "USA", "value": 110.5, "year": 2021},
    ]
