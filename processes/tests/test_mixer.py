# Copyright (c) 2026 Roman Sutormin. MIT License.

import json

import mixer


def test_repo_root_finds_this_checkout():
    root = mixer.repo_root()
    assert (root / "data").is_dir()
    assert (root / "processes").is_dir()
    assert (root / "frontend").is_dir()


def test_load_world_metrics_keeps_world_scope_and_sorts_by_key(tmp_path):
    _write(tmp_path / "zeta.json", _document("zeta", "World"))
    _write(tmp_path / "alpha.json", _document("alpha", "World", country="Türkiye"))
    _write(tmp_path / "europe.json", _document("europe_house", "Europe"))
    _write(tmp_path / "bare.json", {"values": [1]})
    _write(tmp_path / "text-metadata.json", {"metadata": "World"})
    _write(tmp_path / "list.json", [1, 2, 3])
    europe = tmp_path / "europe"
    europe.mkdir()
    _write(europe / "nested_world.json", _document("nested", "World"))

    documents = mixer.load_world_metrics(tmp_path)

    assert [document["metadata"]["key"] for document in documents] == ["alpha", "zeta"]
    assert documents[0]["data"][0]["country"] == "Türkiye"


def test_mix_writes_a_json_array(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "processes").mkdir()
    _write(root / "data" / "life.json", _document("life_expectancy", "World"))
    _write(root / "data" / "prices.json", _document("inflation_rate", "World"))
    monkeypatch.setattr(mixer, "repo_root", lambda: root)

    destination = mixer.mix()

    assert destination == root / "frontend" / "src" / "world-metrics.json"
    text = destination.read_text(encoding="utf-8")
    assert text.endswith("\n")
    documents = json.loads(text)
    assert [document["metadata"]["key"] for document in documents] == [
        "inflation_rate",
        "life_expectancy",
    ]


def test_main_prints_the_written_keys(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "processes").mkdir()
    _write(root / "data" / "life.json", _document("life_expectancy", "World"))
    monkeypatch.setattr(mixer, "repo_root", lambda: root)

    mixer.main()

    output = capsys.readouterr().out
    assert "Wrote 1 World-scope metrics" in output
    assert "life_expectancy" in output


def _document(key: str, scope: str, country: str = "France") -> dict:
    return {
        "metadata": {"key": key, "scope": scope},
        "data": [{"country": country, "code": "FRA", "value": 1, "year": 2021}],
    }


def _write(path, document) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")
