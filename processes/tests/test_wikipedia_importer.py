import pandas as pd
import pytest

from importers.wikipedia_importer import (
    WikipediaImporter,
    _country_codes,
    _english_rows,
    _english_speakers_table,
    _fixed_year_rows,
    _immigrant_columns,
    _immigrant_share_table,
    _opposition_columns,
    _opposition_poll_table,
    _percent,
    _survey_year,
)


def test_percent_reads_the_total_share():
    assert _percent("95.88%") == 95.88
    assert _percent("19%") == 19
    assert _percent("?") is None
    assert _percent("120%") is None


def test_selects_the_country_percent_table_and_ignores_banners():
    banner = pd.DataFrame({0: ["This article needs more citations."]})
    countries = pd.DataFrame(
        {
            "Country": [f"Country {index}" for index in range(12)],
            "Total\xa0%": ["10%"] * 12,
            "Notes / Sources": ["2020"] * 12,
        }
    )

    selected = _english_speakers_table([banner, countries])

    assert len(selected) == 12
    assert list(selected.columns) == ["Country", "Total\xa0%", "Notes / Sources"]


def test_english_rows_keep_the_latest_cited_year_and_known_countries():
    frame = pd.DataFrame(
        {
            "Country": ["United States", "France", "Bonaire", "Fiji"],
            "Total %": ["95.88%", "39.5%", "80%", "?"],
            "Notes / Sources": [
                "1990 census, revised 2022",
                "no date here",
                "2019",
                "2018",
            ],
        }
    )

    rows = _english_rows(frame, {"United States": "USA", "France": "FRA"}, 2026)

    assert rows == [
        {"country": "United States", "code": "USA", "value": 95.88, "year": 2022},
        {"country": "France", "code": "FRA", "value": 39.5, "year": 2026},
    ]


def test_to_documents_uses_the_newest_year_for_each_country():
    frame = pd.DataFrame(
        {
            "Country": ["France", "France"],
            "Total %": ["30%", "39.5%"],
            "Notes / Sources": ["2012", "2021"],
        }
    )
    documents = dict(WikipediaImporter(include_series=True).to_documents(frame))
    metric = documents["english_speaking_population"]

    assert metric["metadata"]["description"] == "Percent of English-speaking population"
    assert "(" not in metric["metadata"]["description"]
    assert metric["metadata"]["units"] == "%"
    assert metric["metadata"]["reversedScale"] is False
    assert metric["metadata"]["scope"] == "World"
    assert metric["metadata"]["source"] == "Wikipedia"
    assert metric["data"] == [
        {"country": "France", "code": "FRA", "value": 39.5, "year": 2021},
    ]
    assert [entry["year"] for entry in metric["series"]] == [2012, 2021]
    assert set(documents) == {"english_speaking_population"}


def test_country_table_is_required():
    with pytest.raises(ValueError, match="English-speaking population table"):
        _english_speakers_table([pd.DataFrame({"Country": ["France"], "Total %": ["1%"]})])


def test_map_names_include_wikipedia_aliases():
    codes = _country_codes()

    assert codes["United States"] == "USA"
    assert codes["France"] == "FRA"
    assert codes["Czech Republic"] == "CZE"
    assert codes["St. Lucia"] == "LCA"
    assert codes["Brunei Darussalam"] == "BRN"
    assert codes["United Republic of Tanzania"] == "TZA"


def test_opposition_poll_uses_the_fewer_or_none_column():
    too_high = pd.DataFrame(
        {
            "Country": ["Germany", "Spain", "Sweden", "United Kingdom", "Italy", "France", "Denmark"],
            "Too high (%)": [81, 80, 73, 71, 71, 69, 55],
        }
    )
    fewer = pd.DataFrame(
        {
            "Country/territory": [f"Country {index}" for index in range(12)],
            "Fewer/none (%)": list(range(12, 24)),
            "More (%)": [10] * 12,
        }
    )

    selected = _opposition_poll_table([too_high, fewer])

    assert list(selected.columns) == ["Country/territory", "Fewer/none (%)", "More (%)"]
    assert _survey_year("In 2018, a survey of 27 countries wanted fewer immigrants.", 2026) == 2018
    assert _survey_year("no survey sentence here", 2026) == 2026


def test_opposition_rows_keep_the_survey_year_and_skip_unmapped_names():
    frame = pd.DataFrame(
        {
            "Country/territory": ["Greece", "United States", "Caribbean"],
            "Fewer/none (%)": [82, "29[1]", 10],
        }
    )

    rows = _fixed_year_rows(frame, {"Greece": "GRC", "United States": "USA"}, _opposition_columns, 2018, "opposition poll")

    assert rows == [
        {"country": "Greece", "code": "GRC", "value": 82.0, "year": 2018},
        {"country": "United States", "code": "USA", "value": 29.0, "year": 2018},
    ]


def test_immigrant_share_ignores_the_emigrant_list_and_reads_the_stock_year():
    emigrants = pd.DataFrame(
        {
            "Country or region of origin": ["World"] + [f"Origin {index}" for index in range(25)],
            "Emigrants": [100] * 26,
        }
    )
    immigrants = pd.DataFrame(
        {
            "Country or territory": ["Andorra", "United States", "Caribbean"] + [f"Place {index}" for index in range(19)],
            "Immigrants 2024[3]": ["48,408", "52,375,881", "1"] + ["10"] * 19,
            "Percentage of total population": [54.36, "15.2[2]", None] + [1.5] * 19,
        }
    )
    older = pd.DataFrame(
        {
            "Country or territory": [f"Older {index}" for index in range(20)],
            "Immigrants 2020[1]": ["10"] * 20,
            "Percentage of total population": [1.5] * 20,
        }
    )

    selected, year = _immigrant_share_table([emigrants, older, immigrants])

    assert year == 2024
    assert _immigrant_columns(selected)[1] == "Percentage of total population"
    rows = _fixed_year_rows(
        selected,
        {"Andorra": "AND", "United States": "USA"},
        _immigrant_columns,
        year,
        "immigrant share",
    )
    assert rows == [
        {"country": "Andorra", "code": "AND", "value": 54.36, "year": 2024},
        {"country": "United States", "code": "USA", "value": 15.2, "year": 2024},
    ]
