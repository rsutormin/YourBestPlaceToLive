# Copyright (c) 2026 Roman Sutormin. MIT License.

import pytest

from importers.bis_importer import CATEGORIES as BIS_CATEGORIES
from importers.eurostat_importer import CATEGORIES as EUROSTAT_CATEGORIES
from importers.heritage_importer import CATEGORIES as HERITAGE_CATEGORIES
from importers.oecd_importer import CATEGORIES as OECD_CATEGORIES
from importers.open_meteo_importer import CATEGORIES as OPEN_METEO_CATEGORIES
from importers.owid_importer import CATEGORIES as OWID_CATEGORIES
from importers.vdem_importer import CATEGORIES as VDEM_CATEGORIES
from importers.wikipedia_importer import CATEGORIES as WIKIPEDIA_CATEGORIES
from importers.world_bank_importer import CATEGORIES as WORLD_BANK_CATEGORIES


EXPORTED = (
    ("World Bank", WORLD_BANK_CATEGORIES),
    ("Eurostat", EUROSTAT_CATEGORIES),
    ("Heritage Foundation", HERITAGE_CATEGORIES),
    ("OECD", OECD_CATEGORIES),
    ("OWID", OWID_CATEGORIES),
    ("V-Dem", VDEM_CATEGORIES),
    ("Wikipedia", WIKIPEDIA_CATEGORIES),
    ("BIS", BIS_CATEGORIES),
    ("Open-Meteo", OPEN_METEO_CATEGORIES),
)


@pytest.mark.parametrize(("source", "categories"), EXPORTED)
def test_exported_indicators_have_unique_keys_and_summaries(source, categories):
    indicators = [
        indicator
        for category in categories
        for indicator in category["indicators"]
        if indicator.get("export", True)
    ]
    keys = [indicator["key"] for indicator in indicators]

    assert len(keys) == len(set(keys)), source
    for indicator in indicators:
        assert "(" not in indicator["name"], indicator["key"]
        assert isinstance(indicator["reversed_scale"], bool)
        assert indicator["importance"] in {0, 0.25, 0.5, 0.75, 1}
        words = indicator["summary"].split()
        assert 20 <= len(words) <= 45, indicator["key"]


def test_removed_metrics_stay_out_of_the_catalogs():
    world_bank = _keys(WORLD_BANK_CATEGORIES)
    bis = _keys(BIS_CATEGORIES)
    oecd = _exported_keys(OECD_CATEGORIES)

    assert "ppp_conversion_factor" not in world_bank
    assert bis == ["real_house_price_index"]
    assert "overtime_workers" not in oecd
    assert "total_workers" not in oecd
    assert "overtime_workers_percentage" in _keys(OECD_CATEGORIES)


def _keys(categories) -> list[str]:
    return [indicator["key"] for category in categories for indicator in category["indicators"]]


def _exported_keys(categories) -> list[str]:
    return [
        indicator["key"]
        for category in categories
        for indicator in category["indicators"]
        if indicator.get("export", True)
    ]
