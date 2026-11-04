import asyncio
import json
from types import SimpleNamespace

import pandas as pd

from mediapos.linking import (
    ModelCache,
    WikidataCache,
    entity_tables,
    fits,
    is_vague,
    rule_pick,
    search_candidates,
    sentence_around,
    summarize,
)


def claim(prop, *ids):
    values = [{"mainsnak": {"datavalue": {"value": {"id": i}}}} for i in ids]
    return {prop: values}


def entity(description="", **props):
    claims = {}
    for prop, ids in props.items():
        claims.update(claim(prop, *ids))
    return {
        "labels": {"de": {"value": "x"}},
        "descriptions": {"de": {"value": description}},
        "claims": claims,
    }


def candidate(qid, human=False, place=False, swiss=True, kind=False):
    return {
        "qid": qid,
        "human": human,
        "place": place,
        "swiss": swiss,
        "class": kind,
        "label": qid,
        "description": "",
        "classes": [],
    }


def test_a_party_is_a_swiss_organization():
    s = summarize("Q1", entity(P31=["Q7278"], P17=["Q39"], P159=["Q70"]))
    assert s["swiss"]
    assert fits("organization", s)
    assert not fits("person", s)


def test_a_hamlet_with_coordinates_and_no_headquarters_is_a_place():
    s = summarize("Q1", entity(P31=["Q11183787"], P625=["c"], P131=["Q11"]))
    assert s["place"]
    assert not fits("organization", s)


def test_a_class_never_fits():
    s = summarize("Q1", entity("kommunales Verwaltungsorgan", P279=["Q2"]))
    assert s["class"]
    assert not fits("organization", s)
    assert not fits("person", s)


def test_rule_pick_needs_exactly_one_swiss_fit():
    swiss = candidate("Q1", human=True)
    other = candidate("Q2", human=True, swiss=False)
    assert rule_pick("person", [swiss, other]) == ("Q1", "rule")
    assert rule_pick("person", [other]) == (None, "ambiguous")
    assert rule_pick("person", [swiss, candidate("Q3", human=True)]) == (
        None,
        "ambiguous",
    )


def test_rule_pick_for_places_and_empty_candidates():
    assert rule_pick("organization", [candidate("Q1", place=True)]) == ("Q1", "place")
    assert rule_pick("person", [candidate("Q1", place=True)]) == (None, "none")
    assert rule_pick("person", []) == (None, "none")


def test_sentence_around_finds_the_sentence():
    text = "Erster Satz. Die SVP verliert. Dritter Satz."
    assert sentence_around(text, 17, 20) == "Die SVP verliert."


def test_answers_are_fetched_once_and_read_back_from_disk(tmp_path):
    calls = []

    def fetch(params):
        calls.append(params)
        return {"search": [{"id": "Q1"}]}

    path = tmp_path / "wd.jsonl"
    wd = WikidataCache(path, fetch=fetch)
    assert wd.search("SVP") == ["Q1"]
    assert wd.search("SVP") == ["Q1"]
    assert len(calls) == 1
    assert WikidataCache(path, fetch=fetch).search("SVP") == ["Q1"]
    assert len(calls) == 1


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.headers = (
            payload,
            status,
            {"Retry-After": 0},
        )
        self.ok = status == 200

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def test_an_error_answer_is_retried_and_never_returned(tmp_path):
    wd = WikidataCache(tmp_path / "wd.jsonl")
    answers = [
        Response({"error": {"code": "cirrussearch-too-busy-error"}}),
        Response({}, status=429),
        Response({"search": []}),
    ]
    wd.session = SimpleNamespace(get=lambda *a, **k: answers.pop(0))
    wd.last = 0.0
    assert wd._fetch({"action": "x"}, pace=0) == {"search": []}
    assert answers == []


def test_search_tries_key_and_spellings_and_merges_candidates(tmp_path):
    hits = {"ignazio cassis": ["Q1"], "cassis": ["Q2", "Q1"]}

    def fetch(params):
        return {"search": [{"id": q} for q in hits[params["search"]]]}

    wd = WikidataCache(tmp_path / "wd.jsonl", fetch=fetch)
    found = search_candidates(wd, {"P:ignazio cassis": ["Cassis", "Ignazio Cassis"]})
    assert found == {"P:ignazio cassis": ["Q1", "Q2"]}


def test_model_answers_are_cached_by_request(tmp_path):
    calls = []

    async def create(**request):
        calls.append(request)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps({"name": "x"}))],
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        )

    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    async def run():
        cache = ModelCache(tmp_path / "m.jsonl")
        gate = asyncio.Semaphore(1)
        first = await cache.ask(client, gate, {"system": "a"})
        again = await cache.ask(client, gate, {"system": "a"})
        return first, again

    first, again = asyncio.run(run())
    assert first == again
    assert first["answer"] == {"name": "x"}
    assert len(calls) == 1


def test_vague_means_lone_surnames_and_generic_bodies():
    frame = pd.DataFrame(
        {
            "actor": ["P:sommaruga", "O:parlament", "O:svp"],
            "status": ["partial", "organization", "organization"],
        }
    )
    assert is_vague(frame).tolist() == [True, True, False]


def test_actors_with_one_qid_merge_and_counts_add_up():
    resolved = pd.DataFrame(
        {
            "id": ["1", "1", "2", "2"],
            "actor": ["O:svp", "O:volkspartei", "O:svp", "P:maerki"],
            "mention": ["SVP", "Volkspartei", "SVP", "Maerki"],
        }
    )
    links = pd.DataFrame(
        {
            "actor": ["O:svp", "O:volkspartei", "P:maerki"],
            "qid": ["Q1", "Q1", None],
            "label": ["SVP", "SVP", None],
            "description": ["Partei", "Partei", None],
        }
    )
    articles = pd.DataFrame({"id": ["1", "2"], "medium_code": ["A", "B"]})
    linked, per_article, entities = entity_tables(resolved, links, articles)
    totals = entities.set_index("entity")["mentions"].to_dict()
    assert totals == {"Q1": 3, "P:maerki": 1}
    assert per_article["mentions"].sum() == len(linked) == 4
    assert entities.set_index("entity").loc["P:maerki", "label"] == "maerki"
