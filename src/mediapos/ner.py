"""Named entities: Haiku inline tags, plus spaCy and GLiNER for comparison.

Exploratory code for notebooks 02 and 03. One row per mention: article, model,
character position, mention, type. spaCy and GLiNER are imported where they run,
so that the Haiku path does not load them.
"""

from __future__ import annotations

import asyncio
import collections
import difflib
import hashlib
import json
import re

import anthropic
import numpy as np
import pandas as pd

from .config import DATA_INTERIM
from .relevance import CONCURRENCY, MODEL, cost

COLUMNS = ["id", "model", "start", "end", "mention", "type", "label", "score"]
SPACY_MODEL = "de_core_news_lg"
SPACY_TYPES = {"PER": "person", "ORG": "organization"}
GLINER_MODEL = "urchade/gliner_multi-v2.1"
GLINER_LABELS = ["person", "organization"]
GLINER_THRESHOLD = 0.5
GLINER_MAX_WORDS = 150  # GLiNER reads at most 384 of its tokens


def config_sha(config: object) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]


def cached(name: str, config: object, run, frame: pd.DataFrame) -> pd.DataFrame:
    """Run a local model once per config; later calls read the saved mentions."""
    path = DATA_INTERIM / f"a631_ner_{name}_{config_sha(config)}.parquet"
    ids = path.with_suffix(".ids.json")
    if path.exists() and set(frame["id"]) <= set(json.loads(ids.read_text())):
        saved = pd.read_parquet(path)
        return saved[saved["id"].isin(frame["id"])].reset_index(drop=True)
    mentions = run(frame)
    mentions.to_parquet(path, index=False)
    ids.write_text(json.dumps(sorted(frame["id"])))
    return mentions


def chunks(text: str, max_words: int) -> list[tuple[int, int]]:
    """(start, end) spans of at most max_words words, cut at the last sentence or line end."""
    words = [m.span() for m in re.finditer(r"\S+", text)]
    spans, first, cut = [], 0, None
    for i, (s, e) in enumerate(words):
        if i - first == max_words:
            j = cut if cut is not None and cut > first else i
            spans.append((words[first][0], words[j - 1][1]))
            first, cut = j, None
        if re.search(r"[.!?:;»«\"“”]$", text[s:e]) or text[e : e + 1] == "\n":
            cut = i + 1
    if first < len(words):
        spans.append((words[first][0], words[-1][1]))
    return spans


def run_spacy(frame: pd.DataFrame) -> pd.DataFrame:
    import spacy

    nlp = spacy.load(SPACY_MODEL)
    rows = [
        (
            i,
            "spacy",
            e.start_char,
            e.end_char,
            e.text,
            SPACY_TYPES.get(e.label_, "other"),
            e.label_,
            np.nan,
        )
        for i, doc in zip(frame["id"], nlp.pipe(frame["text"], batch_size=16), strict=False)
        for e in doc.ents
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def run_gliner(frame: pd.DataFrame) -> pd.DataFrame:
    from gliner import GLiNER

    model = GLiNER.from_pretrained(GLINER_MODEL)
    pieces = [
        (i, s, text[s:e])
        for i, text in zip(frame["id"], frame["text"], strict=False)
        for s, e in chunks(text, GLINER_MAX_WORDS)
    ]
    found = model.inference(
        [p[2] for p in pieces], GLINER_LABELS, threshold=GLINER_THRESHOLD, batch_size=16
    )
    rows = [
        (
            i,
            "gliner",
            offset + p["start"],
            offset + p["end"],
            p["text"],
            p["label"],
            p["label"],
            p["score"],
        )
        for (i, offset, _), predictions in zip(pieces, found, strict=False)
        for p in predictions
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def spacy_mentions(frame: pd.DataFrame) -> pd.DataFrame:
    import spacy

    version = spacy.load(SPACY_MODEL).meta["version"]
    return cached("spacy", [SPACY_MODEL, version], run_spacy, frame)


def gliner_mentions(frame: pd.DataFrame) -> pd.DataFrame:
    config = [GLINER_MODEL, GLINER_LABELS, GLINER_THRESHOLD, GLINER_MAX_WORDS]
    return cached("gliner", config, run_gliner, frame)


TAG_SYSTEM = """You mark named entities in one piece of a Swiss German-language news article.

Copy the piece exactly, character for character, and wrap every mention of a person or \
an organization in a tag: <e id="P1">...</e> for persons, <e id="O1">...</e> for \
organizations. Change nothing else: no corrections, no added or removed characters, \
spaces, line breaks or punctuation. Output only the tagged piece.

Same entity, same id. You get the table of entities already found earlier in the \
article: reuse those ids, also when the entity is written differently ("Moser" after \
"Tiana Angelina Moser", "des Gewerbeverbands" after "Gewerbeverband"). A new entity gets \
the next free number: P for persons, O for organizations.

What to tag:
- full names, surnames or first names alone, abbreviations, and names in any \
grammatical form;
- a party or organization abbreviation inside a compound word, tagged on its own: \
<e id="O1">FDP</e>-Chefin, <e id="O2">SVP</e>-Initiative;
- organizations include political parties, government bodies (Bundesrat, Parlament, \
Nationalrat), companies, associations, unions, media outlets and international bodies \
such as the EU.

What not to tag: pronouns; role words without a name ("die Bundesrätin"); a title before \
a name, which stays outside the tag (Bundesrätin <e id="P2">Karin Keller-Sutter</e>); \
places; events; laws and ballot proposals; the journalist who wrote the article.

Tags are never nested."""
TAG = re.compile(r'<e id="([PO]\d+)">(.*?)</e>', re.DOTALL)
TAG_PIECE_WORDS = 400
TAG_RETRIES = 2
TAG_MAX_LOST = (
    0.5  # a copy that skips more than this is retried; the best attempt is then patched
)
TAG_PATCH_DEPTH = 2  # skipped passages are re-tagged, and their skips once more
TAG_SHA = config_sha(
    [
        MODEL,
        TAG_SYSTEM,
        TAG_PIECE_WORDS,
        TAG_MAX_LOST,
        TAG_PATCH_DEPTH,
        "adaptive",
        "medium",
    ]
)
TAG_CACHE = DATA_INTERIM / "a631_ner_haiku_tags.jsonl"


def untag(tagged: str) -> tuple[str, list[tuple[int, int, str]]]:
    """Plain text and (start, end, entity id) of every tag, positions in the plain text."""
    plain, spans, last = [], [], 0
    for m in TAG.finditer(tagged):
        plain.append(tagged[last : m.start()])
        start = sum(map(len, plain))
        plain.append(m.group(2))
        spans.append((start, start + len(m.group(2)), m.group(1)))
        last = m.end()
    plain.append(tagged[last:])
    return "".join(plain), spans


def align(piece: str, plain: str, spans) -> tuple[list, int, list[tuple[int, int]]]:
    """Carry tags from the model's copy back onto the original piece.

    The model sometimes edits while copying (a corrected case ending, an added
    word, a skipped headline). Aligning copy and original maps each tag to its
    original position; a tag is kept only if its text sits unchanged inside one
    aligned block, so every kept mention is verified against the original. Text
    the model adds matches nothing in the original, so no tag can come from it.
    Text it skips is what costs mentions: those stretches come back as gaps,
    widened to whole words, so they can be tagged in a second pass.
    Returns the kept spans, the number of dropped tags and the gaps.
    """
    blocks = difflib.SequenceMatcher(
        None, plain, piece, autojunk=False
    ).get_matching_blocks()
    kept = []
    for s, e, eid in spans:
        block = next((b for b in blocks if b.a <= s and e <= b.a + b.size), None)
        if block is not None:
            kept.append((block.b + s - block.a, block.b + e - block.a, eid))
    gaps, covered = [], 0
    for b in sorted(blocks, key=lambda b: b.b):
        if b.b > covered:
            gaps.append((covered, b.b))
        covered = max(covered, b.b + b.size)
    widened = []
    for a, z in gaps:
        gap = piece[a:z]
        a, z = a + len(gap) - len(gap.lstrip()), z - len(gap) + len(gap.rstrip())
        if a >= z:
            continue  # only whitespace was lost
        a = max(piece.rfind(" ", 0, a), piece.rfind("\n", 0, a)) + 1
        z = min(
            [i for i in (piece.find(" ", z), piece.find("\n", z)) if i != -1]
            or [len(piece)]
        )
        if not re.search(r"\w", piece[a:z]):
            continue
        if widened and a <= widened[-1][1]:
            widened[-1] = (widened[-1][0], max(z, widened[-1][1]))
        else:
            widened.append((a, z))
    return kept, len(spans) - len(kept), widened


def table_lines(names: dict[str, str]) -> str:
    if not names:
        return "(none yet)"
    order = sorted(names, key=lambda i: (i[0], int(i[1:])))
    return "\n".join(f"{i} = {names[i]}" for i in order)


def update_names(names: dict[str, str], text: str, spans) -> None:
    """An entity's name in the table is the longest form it has been tagged with."""
    for s, e, eid in spans:
        if len(text[s:e]) > len(names.get(eid, "")):
            names[eid] = text[s:e]


async def tag_piece(client, piece: str, names: dict[str, str], depth: int = 0):
    """Tag one piece. Passages the copy skipped are tagged again on their own.

    Returns the spans, the token and repair counts, and an error or None.
    """
    used = dict.fromkeys(
        [
            "input_tokens",
            "output_tokens",
            "attempts",
            "dropped_tags",
            "patched_chars",
            "missing_chars",
        ],
        0,
    )
    best, best_lost = None, 0
    for _ in range(1 + TAG_RETRIES):
        used["attempts"] += 1
        response = await client.messages.create(
            model=MODEL,
            max_tokens=16_000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=TAG_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Entities already found in this article:\n{table_lines(names)}\n\n"
                    f"Piece:\n{piece}",
                }
            ],
        )
        used["input_tokens"] += response.usage.input_tokens
        used["output_tokens"] += response.usage.output_tokens
        if response.stop_reason != "end_turn":
            continue
        tagged = next((b.text for b in response.content if b.type == "text"), "")
        attempt = align(piece, *untag(tagged))
        lost = sum(z - a for a, z in attempt[2])
        if best is None or lost < best_lost:
            best, best_lost = attempt, lost
        if lost <= TAG_MAX_LOST * len(piece):
            break  # good enough: whatever it skipped is patched below
    if best is None:
        return [], used, "no finished answer for the piece"
    spans, dropped, gaps = best  # the best copy; its skipped passages are patched below
    used["dropped_tags"] += dropped
    if depth == TAG_PATCH_DEPTH:
        used["missing_chars"] += sum(z - a for a, z in gaps)
        return spans, used, None
    local = dict(names)
    update_names(local, piece, spans)
    for a, z in gaps:
        sub, sub_used, error = await tag_piece(client, piece[a:z], local, depth + 1)
        for k in sub_used:
            used[k] += sub_used[k]
        if error:
            return [], used, error
        spans = [x for x in spans if x[1] <= a or x[0] >= z] + [
            (a + s, a + e, i) for s, e, i in sub
        ]
        used["patched_chars"] += z - a
    return sorted(spans), used, None


async def tag_article(client, article_id: str, text: str) -> dict:
    """Tag an article piece by piece, carrying the entity table forward."""
    names, mentions = {}, []
    used = dict.fromkeys(
        [
            "input_tokens",
            "output_tokens",
            "attempts",
            "dropped_tags",
            "patched_chars",
            "missing_chars",
        ],
        0,
    )
    for start, end in chunks(text, TAG_PIECE_WORDS):
        spans, piece_used, error = await tag_piece(client, text[start:end], names)
        for k in piece_used:
            used[k] += piece_used[k]
        if error:
            return {"id": article_id, "sha": TAG_SHA, "error": error, **used}
        spans = [(start + s, start + e, eid) for s, e, eid in spans]
        update_names(names, text, spans)
        mentions += spans
    return {
        "id": article_id,
        "sha": TAG_SHA,
        "entities": names,
        "mentions": mentions,
        **used,
    }


def tag_results() -> dict[str, dict]:
    if not TAG_CACHE.exists():
        return {}
    rows = (json.loads(line) for line in TAG_CACHE.read_text().splitlines())
    return {
        r["id"]: r for r in rows if r["sha"] == TAG_SHA
    }  # a later line for the same id wins


async def tag_missing(frame: pd.DataFrame) -> list[str]:
    done = tag_results()
    todo = frame[[i not in done or "error" in done[i] for i in frame["id"]]]
    if todo.empty:
        return []
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(client, article_id, text, sink):
        async with gate:
            try:
                row = await tag_article(client, article_id, text)
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                return f"{article_id}: {type(e).__name__}"
        sink.write(json.dumps(row) + "\n")
        sink.flush()
        return f"{article_id}: {row['error']}" if "error" in row else None

    async with anthropic.AsyncAnthropic() as client:
        with TAG_CACHE.open("a") as sink:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(one(client, i, t, sink))
                    for i, t in zip(todo["id"], todo["text"], strict=False)
                ]
    return [t.result() for t in tasks if t.result()]


def fill_repeats(text: str, spans) -> list[tuple[int, int, str]]:
    """Untagged occurrences of a form tagged elsewhere in the article, with that form's id.

    Longest form first and never overlapping a tag or another fill, so an untagged
    "Tiana Angelina Moser" is filled once, not also as "Moser". A form tagged with
    several ids takes the one it carries most often.
    """
    taken = [False] * len(text)
    for s, e, _ in spans:
        taken[s:e] = [True] * (e - s)
    ids: dict[str, collections.Counter] = {}
    for s, e, eid in spans:
        ids.setdefault(text[s:e], collections.Counter())[eid] += 1
    filled = []
    for form in sorted(ids, key=len, reverse=True):
        eid = ids[form].most_common(1)[0][0]
        for m in re.finditer(rf"(?<!\w){re.escape(form)}(?!\w)", text):
            if not any(taken[m.start() : m.end()]):
                taken[m.start() : m.end()] = [True] * (m.end() - m.start())
                filled.append((m.start(), m.end(), eid))
    return sorted(filled)


def haiku_mentions(frame: pd.DataFrame, tagged: dict[str, dict]) -> pd.DataFrame:
    """Haiku's tags and the filled-in repeats as mention rows."""
    rows = []
    for i, text in zip(frame["id"], frame["text"], strict=True):
        spans = [tuple(x) for x in tagged[i]["mentions"]]
        found = [(s, e, eid, False) for s, e, eid in spans]
        found += [(s, e, eid, True) for s, e, eid in fill_repeats(text, spans)]
        for s, e, eid, filled in found:
            kind = "person" if eid[0] == "P" else "organization"
            rows.append((i, "haiku", s, e, text[s:e], kind, eid, np.nan, eid, filled))
    return pd.DataFrame(rows, columns=[*COLUMNS, "entity", "filled"])


async def tag_all(frame: pd.DataFrame) -> pd.DataFrame:
    """Tag what the cache lacks, then return Haiku's mentions for `frame`."""
    for failure in await tag_missing(frame):
        print("failed:", failure)
    tagged = tag_results()
    missing = [i for i in frame["id"] if "error" in tagged.get(i, {"error": ""})]
    assert not missing, f"{len(missing)} articles could not be tagged"
    return haiku_mentions(frame, tagged)


def tag_report(frame: pd.DataFrame, found: pd.DataFrame) -> None:
    """Print what the tagging produced, repaired and cost."""
    tagged = tag_results()
    results = [tagged[i] for i in frame["id"]]
    entities = sum(len(r["entities"]) for r in results)
    patched = sum(r["patched_chars"] for r in results)
    missing = sum(r["missing_chars"] for r in results)
    dropped = sum(r["dropped_tags"] for r in results)
    print(f"Haiku: {len(found):,} mentions of {entities:,} entities")
    print(
        f"copy repairs: {patched:,} skipped characters tagged in a second pass, "
        f"{missing:,} left untagged, {dropped} tags dropped"
    )
    print(
        f"filled in: {found['filled'].sum():,} untagged repeats of a tagged form "
        f"({100 * found['filled'].mean():.1f}% of Haiku's mentions, column `filled`)"
    )
    print(cost(results))
