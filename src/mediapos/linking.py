"""Link actors to Wikidata: vague names per article, then one decision per actor.

Exploratory code for notebook 02. Wikidata answers and Haiku answers are cached
on disk; Haiku's cache key is the full request, so any change to a prompt or to
the sentences sent makes a new call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import pandas as pd
import requests

from .actors import key, strip_title
from .config import DATA_INTERIM
from .relevance import MODEL

WIKIDATA_CACHE = DATA_INTERIM / "wikidata_cache.jsonl"
LINK_CACHE = DATA_INTERIM / "a631_link_haiku.jsonl"
API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "mediapos-semester-project/0.1 (ETH Zurich research; python-requests)"
SWITZERLAND = "Q39"
HUMAN = "Q5"
# Instance-of classes that make an entry a place rather than an actor.
PLACE_CLASSES = {
    "Q515",
    "Q1549591",
    "Q3957",
    "Q5119",
    "Q486972",
    "Q6256",
    "Q3624078",
    "Q70208",
    "Q23058",
    "Q15284",
    "Q1637706",
    "Q2074737",
    "Q532",
    "Q5107",
    "Q82794",
    "Q35657",
    "Q1221156",
}
# Organization names whose referent depends on the article (which city, which canton).
GENERIC_ORGS = {
    "parlament",
    "stadtparlament",
    "kantonsparlament",
    "stadtrat",
    "gemeinderat",
    "regierungsrat",
    "regierung",
    "kantonsregierung",
    "stadtregierung",
    "kantonsrat",
    "grosser rat",
    "kantonspolizei",
    "stadtpolizei",
    "kapo",
    "stapo",
    "polizei",
    "gericht",
    "bezirksgericht",
    "obergericht",
}


class WikidataCache:
    """GET requests to the Wikidata API, each answer stored once on disk."""

    def __init__(self, path: Path, fetch=None):
        self.path = path
        self.answers = {}
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line)
                self.answers[row["key"]] = row["answer"]
        self.fetch = fetch or self._fetch
        self.session = None
        self.lock = threading.Lock()

    def _fetch(self, params: dict, attempts: int = 8, pace: float = 1.0) -> dict:
        """One request, at most one per `pace` seconds; on 429/503 or an error answer,
        wait as told (or back off, up to 5 minutes) and retry, so errors are never
        cached. No maxlag: these are reads, and maxlag refuses them whenever the query
        service lags, which can last hours."""
        if self.session is None:
            self.session = requests.Session()
            self.session.headers["User-Agent"] = USER_AGENT
            self.last = 0.0
        for attempt in range(attempts):
            time.sleep(max(0.0, self.last + pace - time.monotonic()))
            self.last = time.monotonic()
            r = self.session.get(API, params={**params, "format": "json"}, timeout=60)
            busy = (
                r.ok and "error" in r.json()
            )  # e.g. cirrussearch-too-busy-error, sent with a 200
            if r.status_code in (429, 503) or busy:
                time.sleep(
                    float(r.headers.get("Retry-After", min(300, 10 * 2**attempt)))
                )
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(
            f"Wikidata kept refusing after {attempts} attempts: {params}"
        )

    def get(self, params: dict) -> dict:
        key = json.dumps(params, sort_keys=True)
        if key not in self.answers:
            answer = self.fetch(params)
            with self.lock:
                self.answers[key] = answer
                with self.path.open("a") as sink:
                    sink.write(json.dumps({"key": key, "answer": answer}) + "\n")
        return self.answers[key]

    def search(self, name: str, limit: int = 7) -> list[str]:
        answer = self.get(
            {
                "action": "wbsearchentities",
                "search": name,
                "language": "de",
                "uselang": "de",
                "type": "item",
                "limit": limit,
            }
        )
        return [c["id"] for c in answer.get("search", [])]

    def entities(self, qids: list[str]) -> dict[str, dict]:
        out = {}
        for k in range(0, len(qids), 50):
            batch = sorted(set(qids[k : k + 50]))
            answer = self.get(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|descriptions|claims",
                    "languages": "de|en",
                }
            )
            out.update(answer.get("entities", {}))
        return out


def claim_ids(entity: dict, prop: str) -> set[str]:
    return {
        c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
        for c in entity.get("claims", {}).get(prop, [])
    } - {None}


def text_of(entity: dict, field: str) -> str:
    values = entity.get(field, {})
    return (values.get("de") or values.get("en") or {}).get("value", "")


def summarize(qid: str, entity: dict) -> dict:
    """The facts the linking decision needs about one candidate."""
    classes = claim_ids(entity, "P31")
    description = text_of(entity, "descriptions")
    claims = entity.get("claims", {})
    swiss = SWITZERLAND in claim_ids(entity, "P27") | claim_ids(entity, "P17") or bool(
        re.search(r"schweiz|swiss", description, re.IGNORECASE)
    )
    # A place: a place class, a population, or coordinates inside a territory without a
    # headquarters (the hamlet 'Grünen', not the party).
    place = (
        bool(classes & PLACE_CLASSES)
        or "P1082" in claims
        or ("P625" in claims and "P131" in claims and "P159" not in claims)
    )
    # A class ('Stadtrat', 'Gewerkschaft') is a kind of thing, never one actor.
    kind_of = "P279" in claims
    return {
        "qid": qid,
        "label": text_of(entity, "labels"),
        "description": description,
        "human": HUMAN in classes,
        "place": place,
        "class": kind_of,
        "swiss": swiss,
        "classes": sorted(classes),
    }


def fits(actor_type: str, candidate: dict) -> bool:
    if candidate["class"]:
        return False
    if actor_type == "person":
        return candidate["human"]
    return not candidate["human"] and not candidate["place"]


def rule_pick(actor_type: str, candidates: list[dict]) -> tuple[str | None, str]:
    """Decide without a model when the answer is unambiguous.

    Returns (qid, method). method: 'rule' when exactly one candidate fits the type
    and is Swiss; 'place' when an organization's best match is a place; 'none'
    when nothing fits; 'ambiguous' when a model must decide. A single foreign
    match is not trusted: a namesake is as likely as the person meant.
    """
    ok = [c for c in candidates if fits(actor_type, c)]
    if not ok:
        if actor_type == "organization" and candidates and candidates[0]["place"]:
            return candidates[0]["qid"], "place"
        return None, "none"
    swiss = [c for c in ok if c["swiss"]]
    if len(swiss) == 1:
        return swiss[0]["qid"], "rule"
    return None, "ambiguous"


def is_generic(mentions: pd.DataFrame) -> pd.Series:
    """Mentions of an organization whose referent depends on the article."""
    actor = mentions["actor"]
    return (actor.str[0] == "O") & actor.str[2:].isin(GENERIC_ORGS)


def is_vague(mentions: pd.DataFrame) -> pd.Series:
    """Mentions to resolve article by article: generic bodies and lone surnames."""
    return (mentions["status"] == "partial") | is_generic(mentions)


def sentence_around(text: str, start: int, end: int, limit: int = 400) -> str:
    """The sentence holding text[start:end], cut to `limit` characters around it."""
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    right = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(right) + 1 if right else len(text)
    sentence = text[left:right].strip()
    if len(sentence) > limit:
        mid = start - left
        sentence = sentence[max(0, mid - limit // 2) : mid + limit // 2]
    return sentence


def cache_key(*parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


class ModelCache:
    """Haiku answers stored once on disk, keyed by a hash of the full request."""

    def __init__(self, path: Path):
        self.path = path
        self.answers = {}
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line)
                self.answers[row["key"]] = row
        self.lock = asyncio.Lock()

    async def ask(self, client, gate, request: dict) -> dict:
        k = cache_key(request)
        if k in self.answers:
            return self.answers[k]
        async with gate:
            response = await client.messages.create(**request)
        text = next((b.text for b in response.content if b.type == "text"), "")
        row = {
            "key": k,
            "stop": response.stop_reason,
            "answer": json.loads(text) if response.stop_reason == "end_turn" else None,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        async with self.lock:
            self.answers[k] = row
            with self.path.open("a") as sink:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


RESOLVE_SYSTEM = """You resolve vague references in Swiss German-language news articles \
from September 2020.

You get a name as it appears in one article, and sentences from that article. Say which \
specific entity the article means:
- for an organization, its full name including the place it belongs to, e.g. \
"Stadtparlament St. Gallen", "Kantonspolizei Thurgau", "Regierungsrat des Kantons Bern", \
or "Bundesversammlung" for the Swiss federal parliament;
- for a person, their first and last name, e.g. "Simonetta Sommaruga".

Use only what the sentences say or clearly imply. If they do not let you tell, answer \
"unknown" as the name.

Also give the entity's type. The type given with the name can be wrong: "SVP" marked \
as a person is the party, an organization."""
RESOLVE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "required": ["name", "type"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ["person", "organization"]},
        },
    },
}

LINK_SYSTEM = """You link names from Swiss German-language news coverage (September 2020, \
around the popular vote on the Begrenzungsinitiative) to their Wikidata entry.

You get the name, how it is written in the articles, sentences where it appears, and \
Wikidata candidates. Answer with the candidate that is the entity the sentences mean. \
Answer "none" if no candidate is that entity, for instance a namesake from another \
country or another field."""


NAME_SYSTEM = """You name entities from Swiss German-language news coverage (September 2020, \
around the popular vote on the Begrenzungsinitiative).

You get a name, how it is written in the articles, and sentences where it appears. Give \
the entity's full official name in the nominative, as its German Wikipedia article \
would be titled: "Sozialdemokratische Partei der Schweiz" for "SP", "Ignazio Cassis" \
for "Cassis", "Gerichtshof der Europäischen Union" for "Europäischen Gerichtshofs". \
Answer "unknown" if the sentences do not tell which entity it is."""
NAME_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "required": ["name"],
        "additionalProperties": False,
        "properties": {"name": {"type": "string"}},
    },
}


def request(system: str, user: str, output_format: dict) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 4_000,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium", "format": output_format},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


def contexts(
    mentions: pd.DataFrame, texts: dict[str, str], per_article: int, articles: int
) -> list[str]:
    """Up to `per_article` distinct sentences from each of up to `articles` articles."""
    out = []
    for article_id, g in list(mentions.groupby("id", sort=False))[:articles]:
        seen = []
        for s, e in zip(g["start"], g["end"], strict=False):
            sentence = sentence_around(texts[article_id], s, e)
            if sentence not in seen:
                seen.append(sentence)
            if len(seen) == per_article:
                break
        out += seen
    return out


async def resolve_vague(
    actor_mentions: pd.DataFrame, texts: dict[str, str], cache: ModelCache, client, gate
) -> pd.DataFrame:
    """Re-key generic organizations and lone surnames article by article.

    Returns the mentions with `actor` replaced where the article tells which entity
    is meant, and a `resolved_from` column holding the vague key it replaced. A
    corrected type moves the actor between persons and organizations even when the
    name stays unknown.
    """
    m = actor_mentions.copy()
    jobs = []
    for (article_id, actor), g in m[is_vague(m)].groupby(["id", "actor"]):
        kind = "person" if actor[0] == "P" else "organization"
        name = g["mention"].value_counts().index[0]
        headline = texts[article_id].split("\n", 1)[0]
        lines = "\n".join(
            f"- {s}" for s in contexts(g, texts, per_article=3, articles=1)
        )
        user = f"Name: {name} ({kind})\nHeadline: {headline}\nSentences:\n{lines}"
        jobs.append((article_id, actor, request(RESOLVE_SYSTEM, user, RESOLVE_FORMAT)))
    answers = await asyncio.gather(*(cache.ask(client, gate, r) for _, _, r in jobs))
    new_key = {}
    for (article_id, actor), row in zip(((i, a) for i, a, _ in jobs), answers, strict=False):
        answer = row["answer"] or {}
        name = answer.get("name", "unknown").strip()
        prefix = {"person": "P", "organization": "O"}.get(answer.get("type"), actor[0])
        if name and name.lower() != "unknown":
            k = strip_title(key(name)) if prefix == "P" else key(name)
        elif prefix != actor[0]:
            k = actor[2:]
        else:
            continue
        new_key[(article_id, actor)] = f"{prefix}:{k}"
    m["resolved_from"] = None
    for (article_id, actor), k in new_key.items():
        rows = (m["id"] == article_id) & (m["actor"] == actor)
        m.loc[rows, "resolved_from"] = actor
        m.loc[rows, "actor"] = k
        m.loc[rows, "status"] = "resolved"
    return m


def search_candidates(
    wd: WikidataCache, names: dict[str, list[str]], limit: int = 12
) -> dict[str, list[str]]:
    """Wikidata search for each actor under its key (the full name for a person),
    its most frequent spelling and its longest one; candidates merged in that order.

    `names` maps an actor to its spellings, most frequent first.
    """
    out = {}
    for actor, spellings in names.items():  # one request at a time, as Wikidata asks
        longest = max(spellings, key=lambda f: (len(f.split()), len(f)))
        queries = dict.fromkeys(
            q.casefold() for q in (actor[2:], spellings[0], longest)
        )
        found = []
        for q in queries:
            found += [x for x in wd.search(q) if x not in found]
        out[actor] = found[:limit]
    return out


def describe(wd: WikidataCache, qids: set[str]) -> tuple[dict, dict]:
    """Summaries of the candidates, and labels of the classes they are instances of."""
    entities = wd.entities(sorted(qids))
    summary = {q: summarize(q, e) for q, e in entities.items() if "missing" not in e}
    class_ids = sorted({c for x in summary.values() for c in x["classes"]})
    class_label = {
        q: (e.get("labels", {}).get("de") or e.get("labels", {}).get("en") or {}).get(
            "value", q
        )
        for q, e in wd.entities(class_ids).items()
    }
    return summary, class_label


async def decide(
    found: dict[str, list[str]],
    linkable: pd.DataFrame,
    spellings: dict[str, list[str]],
    texts: dict[str, str],
    wd: WikidataCache,
    cache: ModelCache,
    client,
    gate,
) -> dict:
    """actor -> (qid, method, summary of the qid): the rule when it is sure, Haiku otherwise."""
    summary, class_label = describe(wd, {q for qs in found.values() for q in qs})
    picks, jobs = {}, []
    for actor, qids in found.items():
        kind = "person" if actor[0] == "P" else "organization"
        candidates = [
            summary[q] for q in qids if q in summary and not summary[q]["class"]
        ]
        picks[actor] = rule_pick(kind, candidates)
        if picks[actor][1] == "ambiguous":
            lines = "\n".join(
                f"- {c['qid']}: {c['label']} — {c['description'] or 'no description'} "
                f"(instance of: {', '.join(class_label.get(x, x) for x in c['classes'][:3]) or '?'})"
                for c in candidates
            )
            sentences = "\n".join(
                f"- {s}"
                for s in contexts(
                    linkable[linkable["actor"] == actor],
                    texts,
                    per_article=1,
                    articles=3,
                )
            )
            user = (
                f"Name: {spellings[actor][0]} ({kind})\nWritten as: {', '.join(spellings[actor][:6])}\n"
                f"Sentences:\n{sentences}\nCandidates:\n{lines}"
            )
            fmt = {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "required": ["qid"],
                    "additionalProperties": False,
                    "properties": {
                        "qid": {
                            "type": "string",
                            "enum": [c["qid"] for c in candidates] + ["none"],
                        }
                    },
                },
            }
            jobs.append((actor, request(LINK_SYSTEM, user, fmt)))
    answers = await asyncio.gather(*(cache.ask(client, gate, r) for _, r in jobs))
    for (actor, _), row in zip(jobs, answers, strict=False):
        qid = (row["answer"] or {}).get("qid", "none")
        picks[actor] = (None, "model: none") if qid == "none" else (qid, "model")
    return {a: (q, how, summary.get(q, {})) for a, (q, how) in picks.items()}


async def official_names(
    actors: list[str],
    linkable: pd.DataFrame,
    spellings: dict[str, list[str]],
    texts: dict[str, str],
    cache: ModelCache,
    client,
    gate,
) -> dict[str, str]:
    """Haiku's official name for each actor, for those it can tell."""
    jobs = []
    for actor in actors:
        kind = "person" if actor[0] == "P" else "organization"
        sentences = "\n".join(
            f"- {s}"
            for s in contexts(
                linkable[linkable["actor"] == actor], texts, per_article=1, articles=3
            )
        )
        user = f"Name: {spellings[actor][0]} ({kind})\nWritten as: {', '.join(spellings[actor][:6])}\nSentences:\n{sentences}"
        jobs.append((actor, request(NAME_SYSTEM, user, NAME_FORMAT)))
    answers = await asyncio.gather(*(cache.ask(client, gate, r) for _, r in jobs))
    names = {
        a: (row["answer"] or {}).get("name", "unknown").strip()
        for (a, _), row in zip(jobs, answers, strict=False)
    }
    return {a: n for a, n in names.items() if n and n.lower() != "unknown"}


async def link_actors(
    actor_mentions: pd.DataFrame,
    texts: dict[str, str],
    wd: WikidataCache,
    cache: ModelCache,
    client,
    gate,
) -> pd.DataFrame:
    """One row per actor: qid, Wikidata label and description, and how it was decided.

    An actor no candidate fits gets a second try: Haiku names it officially ('SP' ->
    'Sozialdemokratische Partei der Schweiz'), that name is searched, and the decision
    is made again over both searches' candidates. A lone surname left unresolved in
    its article is still linked here, from its sentences across articles; only
    generic organizations are not.
    """
    m = actor_mentions
    unresolved = is_generic(m)
    linkable = m[~unresolved]
    spellings = {
        a: g["mention"].value_counts().index.tolist()
        for a, g in linkable.groupby("actor")
    }
    found = search_candidates(wd, spellings)
    picks = await decide(found, linkable, spellings, texts, wd, cache, client, gate)

    missed = [a for a, (q, _, _) in picks.items() if q is None]
    renamed = await official_names(
        missed, linkable, spellings, texts, cache, client, gate
    )
    again = {
        a: list(dict.fromkeys(wd.search(n) + found[a]))[:12] for a, n in renamed.items()
    }
    for a, (q, how, s) in (
        await decide(again, linkable, spellings, texts, wd, cache, client, gate)
    ).items():
        picks[a] = (q, f"renamed, {how}", s)

    links = pd.DataFrame(
        [
            {
                "actor": a,
                "qid": q,
                "method": how,
                "official_name": renamed.get(a),
                "label": s.get("label"),
                "description": s.get("description"),
            }
            for a, (q, how, s) in picks.items()
        ]
    )
    vague = pd.DataFrame(
        {"actor": m.loc[unresolved, "actor"].unique(), "method": "vague"}
    )
    return pd.concat([links, vague], ignore_index=True)


def entity_tables(
    resolved: pd.DataFrame, links: pd.DataFrame, articles: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Merge actors by QID: mentions with `entity`, counts per article, and totals.

    An unlinked actor stays its own entity.
    """
    linked = resolved.merge(links[["actor", "qid"]], on="actor", how="left")
    linked["entity"] = linked["qid"].fillna(linked["actor"])
    with_qid = links.dropna(subset=["qid"]).drop_duplicates("qid").set_index("qid")

    per_article = (
        linked.merge(articles[["id", "medium_code"]], on="id")
        .groupby(["id", "medium_code", "entity"])
        .size()
        .rename("mentions")
        .reset_index()
    )
    entities = (
        linked.groupby("entity")
        .agg(
            mentions=("mention", "size"),
            articles=("id", "nunique"),
            actors=("actor", lambda a: sorted(set(a))),
            spellings=("mention", "nunique"),
        )
        .sort_values("mentions", ascending=False)
        .reset_index()
    )
    entities = entities.join(with_qid[["label", "description"]], on="entity")
    entities["label"] = entities["label"].fillna(entities["entity"].str[2:])
    entities["qid"] = entities["entity"].where(entities["entity"].str.match(r"Q\d+$"))

    # Every mention is counted once, per article and in total.
    assert per_article["mentions"].sum() == len(linked) == entities["mentions"].sum()
    return linked, per_article, entities
