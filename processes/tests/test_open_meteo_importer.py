import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import importers.open_meteo_importer as open_meteo_importer
from importers.open_meteo_importer import (
    COLD_CELSIUS,
    HEAT_CELSIUS,
    RAIN_MM,
    SNOW_CM,
    SUNSHINE_SECONDS,
    WIND_KMH,
    CountryPoint,
    OpenMeteoImporter,
    _append_checkpoint,
    _load_checkpoint,
    _saved_codes,
    capital_coordinate,
    load_countries,
    metric_counts,
    recent_full_years,
)


def test_rejects_an_end_year_before_the_start():
    with pytest.raises(ValueError, match="end_year"):
        OpenMeteoImporter(start_year=2021, end_year=2020, countries=[])


def test_metric_counts_apply_the_daily_thresholds_and_skip_partial_years():
    frame = _year_frame(
        [
            (HEAT_CELSIUS, RAIN_MM, SNOW_CM, WIND_KMH, SUNSHINE_SECONDS, COLD_CELSIUS),
            (HEAT_CELSIUS - 0.1, 0, 0, 0, 0, COLD_CELSIUS + 0.1),
            (float("nan"), float("nan"), float("nan"), float("nan"), float("nan"), float("nan")),
        ]
    )

    assert metric_counts(frame.iloc[:10]) is None
    assert metric_counts(frame) == {
        "sunny_days": 1,
        "rainy_days": 1,
        "snowy_days": 1,
        "extreme_heat_days": 1,
        "extreme_cold_days": 1,
        "extreme_wind_days": 1,
    }


def test_capital_coordinate_prefers_the_capital_in_that_country():
    results = [
        {"name": "Paris", "country_code": "US", "latitude": 33.66, "longitude": -95.56, "feature_code": "PPLA2", "population": 24000},
        {"name": "Lyon", "country_code": "FR", "latitude": 45.75, "longitude": 4.85, "feature_code": "PPLA", "population": 500000},
        {"name": "Paris", "country_code": "FR", "latitude": 48.85341, "longitude": 2.3488, "feature_code": "PPLC", "population": 2138551},
    ]

    latitude, longitude = capital_coordinate(results, "FR")

    assert latitude == pytest.approx(48.85341)
    assert longitude == pytest.approx(2.3488)
    assert capital_coordinate([], "FR") is None


def test_country_coordinates_follow_the_capital(tmp_path: Path):
    countries_path = tmp_path / "countries.json"
    capitals_path = tmp_path / "capitals.json"
    countries_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _feature("FRA", "France", "FR"),
                    _feature("USA", "United States of America", "US"),
                    _feature("NLD", "Netherlands", "NL"),
                    _feature("ATA", "Antarctica", "AQ"),
                ],
            }
        ),
        encoding="utf-8",
    )
    capitals_path.write_text(
        json.dumps({"FRA": "Paris", "USA": "Washington D.C.", "NLD": "Amsterdam"}),
        encoding="utf-8",
    )

    def geocode(capital: str, country_code: str):
        return {
            ("Paris", "FR"): (48.85341, 2.3488),
            ("Washington D.C.", "US"): (38.89511, -77.03637),
            ("Amsterdam", "NL"): (52.37403, 4.88969),
        }.get((capital, country_code))

    countries = {
        country.code: country
        for country in load_countries(countries_path, capitals_path, geocode)
    }

    assert set(countries) == {"ATA", "FRA", "USA", "NLD"}
    assert countries["ATA"].capital == "South Pole"
    assert countries["ATA"].latitude == -90
    assert countries["ATA"].longitude == 0
    assert countries["FRA"].capital == "Paris"
    assert countries["FRA"].latitude == pytest.approx(48.8534)
    assert countries["FRA"].longitude == pytest.approx(2.3488)
    assert countries["USA"].capital == "Washington D.C."
    assert countries["USA"].latitude == pytest.approx(38.8951)
    assert countries["USA"].longitude == pytest.approx(-77.0364)
    assert countries["NLD"].capital == "Amsterdam"
    assert countries["NLD"].latitude == pytest.approx(52.374)
    assert countries["NLD"].longitude == pytest.approx(4.8897)


def test_recent_full_years_stop_before_the_current_year():
    assert recent_full_years(date(2026, 11, 11)) == [2021, 2022, 2023, 2024, 2025]


def test_to_documents_averages_five_full_years(monkeypatch):
    countries = [
        CountryPoint("FRA", "France", 46.6, 2.3),
        CountryPoint("USA", "United States of America", 39.5, -99.1),
    ]
    importer = OpenMeteoImporter(start_year=2020, end_year=2021, countries=countries)
    years = [2021, 2022, 2023, 2024, 2025]
    monkeypatch.setattr(
        "importers.open_meteo_importer.recent_full_years",
        lambda today=None: years,
    )
    frames = {
        "FRA": {year: _counted_frame(hits) for year, hits in zip(years, [10, 15, 20, 25, 30])},
        "USA": {year: _counted_frame(5) for year in years if year != 2023},
    }
    monkeypatch.setattr(importer, "fetch_frames", lambda: frames)

    documents = dict(importer.to_documents())

    assert list(documents) == [
        "sunny_days",
        "rainy_days",
        "snowy_days",
        "extreme_heat_days",
        "extreme_cold_days",
        "extreme_wind_days",
    ]
    sunny = documents["sunny_days"]
    assert sunny["metadata"]["source"] == "Open-Meteo"
    assert sunny["metadata"]["scope"] == "World"
    assert sunny["metadata"]["database"] == "ERA5"
    assert sunny["metadata"]["url"] == "https://open-meteo.com/"
    assert sunny["metadata"]["reversedScale"] is False
    assert sunny["metadata"]["importance"] == 0.25
    assert sunny["metadata"]["units"] == "days"
    assert "(" not in sunny["metadata"]["description"]
    assert "series" not in sunny
    assert sunny["data"] == [
        {"country": "France", "code": "FRA", "value": 20.0, "year": 2025},
    ]
    assert documents["rainy_days"]["metadata"]["reversedScale"] is True
    assert documents["extreme_heat_days"]["metadata"]["code"] == "temperature_2m_max"
    assert documents["extreme_cold_days"]["metadata"]["code"] == "temperature_2m_min"
    assert documents["extreme_cold_days"]["metadata"]["reversedScale"] is True


def test_checkpoint_ignores_a_partial_line_and_requires_every_metric(tmp_path: Path):
    path = tmp_path / "sunny_days.json.tmp"
    path.write_text(
        json.dumps({"country": "France", "code": "FRA", "value": 12.5, "year": 2025})
        + "\n"
        + "{\"country\": \"United States\"",
        encoding="utf-8",
    )

    rows = _load_checkpoint(path)

    assert rows == [{"country": "France", "code": "FRA", "value": 12.5, "year": 2025}]
    assert _saved_codes({"sunny_days": rows, "rainy_days": []}) == set()
    assert _saved_codes({"sunny_days": rows, "rainy_days": rows}) == {"FRA"}


def test_checkpoint_line_is_flushed_before_the_file_is_closed(tmp_path: Path):
    path = tmp_path / "sunny_days.json.tmp"
    handle = path.open("a", encoding="utf-8")
    _append_checkpoint(handle, {"country": "France", "code": "FRA", "value": 1, "year": 2025})

    assert json.loads(path.read_text(encoding="utf-8").strip())["code"] == "FRA"
    handle.close()


def test_run_resumes_from_tmp_files_and_skips_saved_countries(tmp_path: Path, monkeypatch):
    years = [2021, 2022, 2023, 2024, 2025]
    monkeypatch.setattr(open_meteo_importer, "recent_full_years", lambda today=None: years)
    fetched: list[str] = []

    def fetch(_client, country, _start, _end):
        fetched.append(country.code)
        frames = []
        for year in years:
            frame = _counted_frame(10)
            frame["date"] = pd.date_range(f"{year}-01-01", periods=len(frame), freq="D", tz="UTC")
            frames.append(frame)
        return pd.concat(frames, ignore_index=True)

    monkeypatch.setattr(open_meteo_importer, "_fetch_country", fetch)
    output = tmp_path / "data"
    output.mkdir()
    saved = {"country": "France", "code": "FRA", "value": 12.5, "year": 2025}
    for key in _metric_keys():
        (output / f"{key}.json.tmp").write_text(json.dumps(saved) + "\n", encoding="utf-8")
    importer = OpenMeteoImporter(
        output_dir=output,
        countries=[
            CountryPoint("FRA", "France", 48.8, 2.3, "Paris"),
            CountryPoint("USA", "United States of America", 38.9, -77.0, "Washington D.C."),
        ],
    )

    importer.run()

    assert fetched == ["USA"]
    sunny = json.loads((output / "sunny_days.json").read_text(encoding="utf-8"))
    assert [row["code"] for row in sunny["data"]] == ["FRA", "USA"]
    assert sunny["data"][0]["value"] == 12.5
    assert not any(output.glob("*.json.tmp"))


def _metric_keys() -> list[str]:
    return [indicator["key"] for category in open_meteo_importer.CATEGORIES for indicator in category["indicators"]]


def _counted_frame(hits: int) -> pd.DataFrame:
    rows = [(HEAT_CELSIUS, RAIN_MM, SNOW_CM, WIND_KMH, SUNSHINE_SECONDS, COLD_CELSIUS)] * hits
    rows.extend([(0, 0, 0, 0, 0, COLD_CELSIUS + 1)] * (365 - hits))
    return _year_frame(rows)


def _year_frame(rows: list[tuple[float, float, float, float, float, float]]) -> pd.DataFrame:
    padded = list(rows)
    if len(padded) < 365:
        padded.extend([(0, 0, 0, 0, 0, COLD_CELSIUS + 1)] * (365 - len(padded)))
    return pd.DataFrame(
        padded,
        columns=["temp_max", "rain", "snow", "wind_gusts", "sunshine_sec", "temp_min"],
    )


def _feature(code: str, name: str, iso2: str) -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name, "iso_a3": code, "iso_a2": iso2},
        "geometry": None,
    }


def test_load_countries_skips_a_feature_without_an_iso_code(tmp_path: Path):
    path = tmp_path / "countries.json"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Nowhere", "iso_a3": "-99"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_countries(path) == []
