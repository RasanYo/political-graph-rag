import pandas as pd

from mediapos.actors import (
    actors_from_mentions,
    is_junk,
    key,
    organization_keys,
    person_keys,
    strip_ending,
    strip_title,
)


def mentions(rows):
    frame = pd.DataFrame(rows, columns=["id", "entity", "mention"])
    frame["type"] = frame["entity"].str[0].map({"P": "person", "O": "organization"})
    return frame


def test_key_ignores_case_hyphens_spacing_and_quotes():
    assert key("«Operation-Libero»") == key("operation  libero") == "operation libero"


def test_strip_title_keeps_a_lone_title():
    assert strip_title("der bundespräsident ueli maurer") == "ueli maurer"
    assert strip_title("bundesrätin") == "bundesrätin"


def test_strip_ending_needs_a_known_stem():
    assert strip_ending("Blochers", {"blocher"}) == "blocher"
    assert strip_ending("Jonas", {"blocher"}) == "jonas"


def test_is_junk():
    assert is_junk("und")
    assert is_junk("614")
    assert is_junk("Begrenzungsinitiative")
    assert not is_junk("SVP")


def test_a_surname_attaches_to_its_only_full_name():
    frame = pd.DataFrame({"forms": [["cassis"], ["ignazio cassis", "cassis"]]})
    keys = person_keys(frame)
    assert keys["actor"].tolist() == ["ignazio cassis", "ignazio cassis"]
    assert keys["status"].tolist() == ["attached", "full"]


def test_a_surname_with_two_full_names_stays_apart():
    forms = [["sommaruga"], ["simonetta sommaruga"], ["carlo sommaruga"]]
    keys = person_keys(pd.DataFrame({"forms": forms}))
    assert keys.loc[0, "actor"] == "sommaruga"
    assert keys.loc[0, "status"] == "partial"


def test_a_one_off_mixup_is_outvoted():
    forms = [["svp"], ["svp"], ["svp", "schweizerische volkspartei"], ["svp", "fdp"]]
    forms += [["fdp"], ["fdp"], ["fdp"], ["fdp"]]
    target = organization_keys(pd.DataFrame({"forms": forms}))
    assert target["schweizerische volkspartei"] == "svp"
    assert target["svp"] == "svp"
    assert target["fdp"] == "fdp"


def test_a_person_and_an_organization_never_share_a_key():
    found = actors_from_mentions(
        mentions([("1", "P1", "Maurer"), ("1", "O1", "Maurer")])
    )
    assert set(found["actor"]) == {"P:maurer", "O:maurer"}


def test_a_title_alone_is_dropped_and_a_misfiled_spelling_is_split_off():
    rows = [
        ("1", "P1", "Bundesrätin"),
        ("1", "P2", "Ignazio Cassis"),
        ("1", "P2", "Marco Chiesa"),
    ]
    found = actors_from_mentions(mentions(rows))
    assert set(found["actor"]) == {"P:ignazio cassis", "P:marco chiesa"}
