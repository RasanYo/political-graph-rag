"""Is the vote the main subject? Haiku's label, then the hand review.

Exploratory code for notebook 02. Changing the prompt, the model or the
truncation changes `PROMPT_SHA`, so every article is labelled again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import anthropic
import pandas as pd

from .config import DATA_INTERIM, DATA_REVIEW

MODEL = "claude-haiku-5-5"
MAX_BODY_CHARS = 4_000
CONCURRENCY = 10
RELEVANCE_CACHE = DATA_INTERIM / "a631_relevance.jsonl"
REVIEW_FILE = DATA_REVIEW / "a631_relevance_review.csv"

SYSTEM = """You label Swiss German-language news articles from September and October 2020.

On 27 September 2020 Swiss voters decided five federal proposals: the Begrenzungsinitiative \
(the SVP initiative to end free movement of persons with the EU, also called \
Kündigungsinitiative), the hunting law (Jagdgesetz), the purchase of new fighter jets, \
paternity leave, and higher child tax deductions.

Label the article "related" if its main subject is the Begrenzungsinitiative or its direct \
stakes: the campaign, its actors and arguments, the result, or free movement of persons \
with the EU and the bilateral agreements as they bear on this vote.

Label it "not_related" if its main subject is anything else, even when it mentions the \
initiative. That includes articles mainly about one of the other four proposals, roundups \
that cover several of the proposals side by side, and any other topic.

Judge the main subject of the article, not whether the initiative is mentioned."""

LABEL_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": ["related", "not_related"]}},
        "required": ["label"],
        "additionalProperties": False,
    },
}

# Anything that changes the answer changes the key, so stale labels are never reused.
PROMPT_SHA = hashlib.sha256(
    json.dumps([MODEL, SYSTEM, LABEL_FORMAT, MAX_BODY_CHARS]).encode()
).hexdigest()[:12]


def classifier_input(row: pd.Series) -> str:
    return f"Headline: {row['head']}\nSubhead: {row['subhead']}\n\n{row['body'][:MAX_BODY_CHARS]}"


def load_labels() -> dict[str, dict]:
    if not RELEVANCE_CACHE.exists():
        return {}
    rows = (json.loads(line) for line in RELEVANCE_CACHE.read_text().splitlines())
    return {r["id"]: r for r in rows if r["prompt_sha"] == PROMPT_SHA}


async def label_one(
    client: anthropic.AsyncAnthropic, gate: asyncio.Semaphore, row: pd.Series, sink
) -> str | None:
    async with gate:
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=64,
                thinking={"type": "disabled"},
                output_config={"effort": "low", "format": LABEL_FORMAT},
                system=SYSTEM,
                messages=[{"role": "user", "content": classifier_input(row)}],
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            return f"{row['id']}: {type(e).__name__}"
    if response.stop_reason != "end_turn":
        return f"{row['id']}: stop_reason={response.stop_reason}"
    label = json.loads(next(b.text for b in response.content if b.type == "text"))[
        "label"
    ]
    sink.write(
        json.dumps(
            {
                "id": row["id"],
                "label": label,
                "model": MODEL,
                "prompt_sha": PROMPT_SHA,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        )
        + "\n"
    )
    sink.flush()  # each label is on disk as soon as it exists, so an interrupted run loses nothing
    return None


async def label_missing(frame: pd.DataFrame) -> list[str]:
    todo = frame[~frame["id"].isin(load_labels().keys())]
    if todo.empty:
        return []
    RELEVANCE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(CONCURRENCY)
    async with anthropic.AsyncAnthropic() as client:
        with RELEVANCE_CACHE.open("a") as sink:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(label_one(client, gate, row, sink))
                    for _, row in todo.iterrows()
                ]
    return [t.result() for t in tasks if t.result()]


def load_review() -> pd.DataFrame:
    return pd.read_csv(REVIEW_FILE, dtype={"id": str})


def add_labels(vote: pd.DataFrame) -> pd.DataFrame:
    """Add the cached labels as `relevance`; every article must have one."""
    labels = load_labels()
    vote = vote.assign(
        relevance=vote["id"].map({i: r["label"] for i, r in labels.items()})
    )
    assert vote["relevance"].notna().all(), (
        f"{vote['relevance'].isna().sum()} unlabelled"
    )
    return vote


def kept_articles(vote: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    """The articles labelled related that the hand review did not remove."""
    related = vote["relevance"] == "related"
    # The review covers exactly the articles Haiku labelled related.
    assert set(review["id"]) == set(vote.loc[related, "id"])
    removed = review.loc[review["action"] == "remove", "id"]
    return vote[related & ~vote["id"].isin(removed)].reset_index(drop=True)


def cost(rows: list[dict]) -> str:
    """Token totals of cached rows, priced at the Haiku 5.5 list price."""
    used_in = sum(r["input_tokens"] for r in rows)
    used_out = sum(r["output_tokens"] for r in rows)
    price = used_in / 1e6 * 0.10 + used_out / 1e6 * 0.50
    return f"{used_in:,} tokens in, {used_out:,} out ≈ ${price:.2f}"
