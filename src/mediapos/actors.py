"""From Haiku's per-article entities to actors shared across articles.

Exploratory code for notebook 02.
"""

from __future__ import annotations

import collections
import re

import pandas as pd
from spacy.lang.de.stop_words import STOP_WORDS

QUOTES = "’'\"«»‹›“”„"
TITLES = {
    "bundespräsident",
    "bundespräsidentin",
    "bundesrat",
    "bundesrätin",
    "nationalrat",
    "nationalrätin",
    "ständerat",
    "ständerätin",
    "präsident",
    "präsidentin",
    "parteipräsident",
    "parteipräsidentin",
    "regierungsrat",
    "regierungsrätin",
    "stadtpräsident",
    "stadtpräsidentin",
    "gemeindepräsident",
    "gemeindepräsidentin",
    "staatssekretär",
    "staatssekretärin",
    "botschafter",
    "botschafterin",
    "chefunterhändler",
    "chefunterhändlerin",
    "herr",
    "frau",
    "dr.",
    "prof.",
}
BALLOT = re.compile(r"(initiative|gesetz|vorlage|abstimmung|referendum)$")


def key(form: str) -> str:
    """Grouping key of a spelling: case, hyphens, spacing, outer quotes ignored."""
    return re.sub(r"[\s\-]+", " ", form).strip().strip(QUOTES).strip().casefold()


def strip_title(k: str) -> str:
    """'der bundespräsident ueli maurer' -> 'ueli maurer'; a lone title stays."""
    words = k.split()
    while len(words) > 1 and (
        words[0] in TITLES or words[0] in {"der", "die", "den", "dem", "des"}
    ):
        words = words[1:]
    return " ".join(words)


def strip_ending(form: str, known: set[str]) -> str:
    """'Blochers' -> 'Blocher' when the stem is a known key; otherwise unchanged."""
    k = key(form)
    for cut in ("es", "s"):
        if k.endswith(cut) and k[: -len(cut)] in known:
            return k[: -len(cut)]
    return k


def is_junk(form: str) -> bool:
    """Function words, strings without letters, ballot proposals and laws."""
    k = key(form)
    return k in STOP_WORDS or not re.search(r"[^\W\d_]", k) or bool(BALLOT.search(k))


def compatible(form: str, name: str) -> bool:
    """A person spelling fits a name if each of its words is a word of the name."""
    return set(form.split()) <= set(name.split())


def person_keys(entities: pd.DataFrame) -> pd.DataFrame:
    """Actor key and status of each person entity.

    One row per article entity, with its spellings in column `forms`.

    An entity's name is its longest spelling (most words, then most characters).
    Across the corpus, a name that is the word-by-word ending of exactly one longer
    name is attached to it ('Cassis' -> 'ignazio cassis'); with several candidates
    it is ambiguous and stays apart. Status: 'full' for a name of several words,
    'attached' for one attached to a longer name, 'partial' for a single word left
    on its own.
    """
    names = entities["forms"].map(
        lambda forms: max(
            forms, key=lambda f: (len(f.split()), len(f), forms.count(f), f)
        )
    )
    pool = set(names)
    longer = {}
    for n in pool:
        words = n.split()
        hits = {
            m
            for m in pool
            if len(m.split()) > len(words) and m.split()[-len(words) :] == words
        }
        tops = {
            m
            for m in hits
            if not any(
                m != o and o.split()[-len(m.split()) :] == m.split() for o in hits
            )
        }
        if len(tops) == 1:
            longer[n] = tops.pop()
    keys = names.map(lambda n: longer.get(n, n))
    status = [
        ("attached" if n in longer else "full" if len(n.split()) > 1 else "partial")
        for n in names
    ]
    return pd.DataFrame({"actor": keys, "status": status}, index=entities.index)


def organization_keys(entities: pd.DataFrame) -> dict[str, str]:
    """Spelling -> actor key for organizations, by vote across articles.

    In each article entity the head is its spelling seen in the most article
    entities overall; every spelling of the entity votes for that head. A spelling
    goes to the head it voted for most often, and heads chain to their own head.
    """
    seen = collections.Counter(f for forms in entities["forms"] for f in set(forms))
    votes = collections.defaultdict(collections.Counter)
    for forms in entities["forms"]:
        head = max(set(forms), key=lambda f: (seen[f], len(f), f))
        for f in set(forms):
            votes[f][head] += 1
    target = {f: v.most_common(1)[0][0] for f, v in votes.items()}
    resolved = {}
    for f in target:
        path, g = [f], target[f]
        while g != path[-1] and g not in path:
            path.append(g)
            g = target[g]
        resolved[f] = path[-1]
    return resolved


def actors_from_mentions(mentions: pd.DataFrame) -> pd.DataFrame:
    """Add an `actor` column to Haiku's mentions (id, entity, mention, type).

    Junk tags (function words) are dropped. Spellings are reduced to their key and
    stripped of a case ending when the stem is also a key.
    """
    m = mentions[~mentions["mention"].map(is_junk)].copy()
    known = set(m["mention"].map(key))
    m["form"] = m["mention"].map(lambda f: strip_ending(f, known))
    is_p = m["entity"].str[0] == "P"
    m.loc[is_p, "form"] = m.loc[is_p, "form"].map(strip_title)
    m = m[~(is_p & m["form"].isin(TITLES))]  # "Bundesrätin" tagged as a person: no name
    is_p = m["entity"].str[0] == "P"
    # A person spelling that does not fit its entity's longest name was put under the
    # wrong id by Haiku: it becomes an entity of its own in that article.
    longest = (
        m[is_p]
        .groupby(["id", "entity"])["form"]
        .agg(lambda f: max(f, key=lambda x: (len(x.split()), len(x))))
    )
    misfit = [
        p and not compatible(f, longest[(i, e)])
        for p, i, e, f in zip(is_p, m["id"], m["entity"], m["form"], strict=False)
    ]
    m.loc[misfit, "entity"] = m.loc[misfit, "entity"] + "~" + m.loc[misfit, "form"]
    entities = (
        m.groupby(["id", "entity"])["form"].agg(list).rename("forms").reset_index()
    )
    is_person = entities["entity"].str[0] == "P"
    persons = entities[is_person].reset_index(drop=True)
    persons = persons.join(person_keys(persons))
    person = {
        (i, e): (k, st)
        for i, e, k, st in persons[["id", "entity", "actor", "status"]].itertuples(
            index=False
        )
    }
    org = organization_keys(entities[~is_person])
    resolved = [
        person[(i, e)] if e[0] == "P" else (org[f], "organization")
        for i, e, f in zip(m["id"], m["entity"], m["form"], strict=False)
    ]
    m["actor"] = [
        f"{e[0]}:{k}" for e, (k, _) in zip(m["entity"], resolved, strict=False)
    ]  # a person and an org never merge
    m["status"] = [st for _, st in resolved]
    return m


def display_name(group: pd.DataFrame) -> str:
    """Persons: the most frequent spelling with the most words ('Karin Keller-Sutter').
    Organizations: the most frequent spelling ('SVP', not 'SVP Basel-Stadt')."""
    counts = group["mention"].value_counts()
    if group.name[0] == "O":
        return counts.index[0]
    return max(
        counts.index, key=lambda s: (len(strip_title(key(s)).split()), counts[s])
    )


def actor_tables(
    actor_mentions: pd.DataFrame, articles: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The spellings of each actor, its count per article, and one row per actor."""
    variants = (
        actor_mentions.groupby(["actor", "mention"])
        .size()
        .rename("mentions")
        .reset_index()
        .sort_values(["actor", "mentions"], ascending=[True, False])
    )
    per_article = (
        actor_mentions.merge(articles[["id", "medium_code"]], on="id")
        .groupby(["id", "medium_code", "actor"])
        .agg(mentions=("mention", "size"), filled=("filled", "sum"))
        .reset_index()
    )
    table = (
        actor_mentions.groupby("actor")
        .agg(
            status=("status", lambda s: s.mode().iloc[0]),
            mentions=("mention", "size"),
            articles=("id", "nunique"),
            variants=("mention", "nunique"),
        )
        .sort_values("mentions", ascending=False)
        .reset_index()
    )
    names = actor_mentions.groupby("actor")[["mention"]].apply(display_name)
    table.insert(1, "name", table["actor"].map(names))
    table["type"] = table["actor"].str[0].map({"P": "person", "O": "organization"})

    # Every mention lands in exactly one per-article count; totals are a plain sum.
    assert per_article["mentions"].sum() == len(actor_mentions)
    totals = per_article.groupby("actor")["mentions"].sum()
    assert table.set_index("actor")["mentions"].equals(
        totals.reindex(table["actor"]).rename("mentions")
    )
    return variants, per_article, table
