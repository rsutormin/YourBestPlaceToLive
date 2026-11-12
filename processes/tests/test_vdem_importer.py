import io
import zipfile

import pandas as pd
import pytest

from importers.vdem_importer import VdemImporter, _read_dataset, _scores


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        VdemImporter(start_year=2021, end_year=2020)


def test_scores_scale_the_index_and_skip_gaps():
    frame = pd.DataFrame(
        {
            "country_name": ["France", "France", "Nowhere", "Germany", "United States"],
            "country_text_id": ["FRA", "FRA", "not-a-code", "DEU", "USA"],
            "year": [2020, 2021, 2021, 2021, 2019],
            "v2x_libdem": [0.81234, None, 0.5, 0.9, 0.7],
        }
    )

    assert _scores(frame, 2020, 2021) == {
        2020: {"FRA": ("France", 81.234)},
        2021: {"DEU": ("Germany", 90.0)},
    }


def test_to_documents_keeps_the_latest_scaled_score():
    frame = pd.DataFrame(
        {
            "country_name": ["France", "France", "Germany"],
            "country_text_id": ["fra", "FRA", "DEU"],
            "year": [2020, 2021, 2021],
            "v2x_libdem": [0.5, 0.81226, 0.2],
        }
    )
    documents = dict(VdemImporter(start_year=2020, end_year=2021).to_documents(frame))
    metric = documents["political_freedom"]

    assert metric["metadata"]["description"] == "Political freedom"
    assert "(" not in metric["metadata"]["description"]
    assert metric["metadata"]["source"] == "Varieties of Democracy"
    assert metric["metadata"]["scope"] == "World"
    assert metric["metadata"]["code"] == "v2x_libdem"
    assert metric["metadata"]["units"] == "0-100"
    assert metric["metadata"]["reversedScale"] is False
    assert metric["metadata"]["importance"] == 1.0
    assert "CC BY-SA 4.0" in metric["metadata"]["summary"]
    assert metric["data"] == [
        {"country": "France", "code": "FRA", "value": 81.226, "year": 2021},
        {"country": "Germany", "code": "DEU", "value": 20.0, "year": 2021},
    ]
    assert "series" not in metric


def test_read_dataset_uses_the_csv_inside_the_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("notes.pdf", b"not a table")
        archive.writestr(
            "V-Dem-CY-Core.csv",
            "country_name,country_text_id,year,v2x_libdem,other\nFrance,FRA,2021,0.8,9\n",
        )

    frame = _read_dataset(payload.getvalue())

    assert list(frame.columns) == ["country_name", "country_text_id", "year", "v2x_libdem"]
    assert frame.iloc[0]["country_text_id"] == "FRA"
    assert frame.iloc[0]["v2x_libdem"] == 0.8
