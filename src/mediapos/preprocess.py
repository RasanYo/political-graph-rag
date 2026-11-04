"""From a Swissdox archive to the cleaned articles that name a vote.

Exploratory code for notebook 02: German slice, one event. The reader functions
at the end print article text, so their output must never be committed.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pandas as pd

from . import queries
from .config import DATA_OUT, REPO_ROOT

VOTE = re.compile(
    r"Begrenzungs-?initiative|Kündigungs-?initiative|massvollen? Zuwanderung",
    re.IGNORECASE,
)
SIDE_COLUMNS = {"lg": "captions", "ka": "boxes", "nt": "notes"}
DROPPED = ("au", "ur")
LINE_BREAK = re.compile(r"</?(?:p|zt|ld|tx|br|tr|table)\b[^>]*>|</t[dh]>")
ANY_TAG = re.compile(r"<[^>]+>")


def element(tag: str) -> re.Pattern[str]:
    return re.compile(rf"<{tag}\b[^>]*>(.*?)</{tag}>", re.DOTALL)


def to_text(markup: str) -> str:
    """Markup fragment to plain text: one line per block, whitespace collapsed."""
    # Inline tags become a space: "einen<a ...>Bausatz" must not fuse into one word.
    text = html.unescape(ANY_TAG.sub(" ", LINE_BREAK.sub("\n", markup)))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def split_content(markup: str) -> dict[str, str]:
    # Drop first: photo credits also sit inside captions.
    for tag in DROPPED:
        markup = element(tag).sub(" ", markup)
    parts = {}
    for tag, column in SIDE_COLUMNS.items():
        parts[column] = "\n".join(to_text(m) for m in element(tag).findall(markup))
        markup = element(tag).sub("\n", markup)
    parts["body"] = to_text(markup)
    return parts


def event_archive(event_id: str) -> tuple[pd.Series, dict, Path]:
    """The query, the pull receipt and the local archive of one event."""
    query = pd.read_csv(DATA_OUT / "queries.csv").set_index("event_id").loc[event_id]
    receipts = json.loads((DATA_OUT / "pull_receipts.json").read_text())
    receipt = receipts[f"{query.date_from}_{query.date_to}"]
    return query, receipt, REPO_ROOT / receipt["local_path"]


def load_slice(archive: Path, language: str) -> pd.DataFrame:
    """Every row of one language, typed; revised articles still appear several times."""
    rows = (r for r in queries.read_articles(archive) if r["language"] == language)
    articles = pd.DataFrame(rows)
    articles["pubtime"] = pd.to_datetime(articles["pubtime"], utc=True)
    articles["char_count"] = articles["char_count"].astype(int)
    return articles


def keep_longest(articles: pd.DataFrame) -> pd.DataFrame:
    """One row per id: the longest version, ties broken by content_id."""
    order = ["id", "char_count", "content_id"]
    kept = articles.sort_values(order, ascending=[True, False, True])
    return kept.drop_duplicates("id").reset_index(drop=True)


def select_vote(articles: pd.DataFrame) -> pd.DataFrame:
    """The articles naming the initiative, with mention count and headline flag."""
    searchable = (
        articles["head"] + "\n" + articles["subhead"] + "\n" + articles["content"]
    )
    # pandas' str.count drops a compiled pattern's IGNORECASE flag, so use findall.
    counts = searchable.map(lambda s: len(VOTE.findall(s)))
    named = counts > 0
    vote = articles[named].assign(n_vote_mentions=counts[named]).reset_index(drop=True)
    vote["vote_in_head"] = (vote["head"] + " " + vote["subhead"]).str.contains(VOTE)
    return vote


def add_text(vote: pd.DataFrame) -> pd.DataFrame:
    """Add body, side columns and `text`: headline, subhead and body."""
    vote = vote.join(pd.DataFrame(vote["content"].map(split_content).tolist()))
    vote["text"] = [
        "\n\n".join(p for p in (h.strip(), s.strip(), b) if p)
        for h, s, b in zip(vote["head"], vote["subhead"], vote["body"], strict=True)
    ]
    return vote


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def check_text(vote: pd.DataFrame) -> dict[str, int]:
    """Assert that no markup survives and no word is lost; return word totals."""
    leftover_tag = vote["text"].str.contains(r"</?[a-z]+\b[^>]*>")
    leftover_entity = vote["text"].str.contains(r"&[a-z]+;|&#\d+;")
    assert not leftover_tag.any(), vote.loc[leftover_tag, "id"].tolist()
    assert not leftover_entity.any(), vote.loc[leftover_entity, "id"].tolist()
    assert (vote["body"].str.len() > 0).all()

    # Every word of the raw markup must land somewhere: body, a side column, or a
    # dropped tag. Compare word counts, not strings, since whitespace changed.
    dropped = vote["content"].map(
        lambda m: sum(count_words(x) for t in DROPPED for x in element(t).findall(m))
    )
    columns = ["body", *SIDE_COLUMNS.values()]
    kept = vote[columns].map(count_words)
    raw = vote["content"].map(lambda m: count_words(html.unescape(ANY_TAG.sub(" ", m))))
    total = kept.sum(axis=1) + dropped
    assert (total == raw).all(), (total - raw).abs().max()
    return {**kept.sum().to_dict(), "dropped": int(dropped.sum())}


def vote_articles(archive: Path, language: str) -> pd.DataFrame:
    """The whole path from archive to cleaned vote articles."""
    return add_text(select_vote(keep_longest(load_slice(archive, language))))


def show(vote: pd.DataFrame, i: int) -> None:
    """Print article i of `vote` in full: header line, text, then the side columns."""
    row = vote.iloc[i]
    print(
        f"{row['id']}  {row['medium_name']}  {row['pubtime']:%Y-%m-%d}  "
        f"mentions={row['n_vote_mentions']}  in_head={row['vote_in_head']}  "
        f"relevance={row.get('relevance', '–')}\n"
    )
    print(row["text"])
    for column in SIDE_COLUMNS.values():
        if row[column]:
            print(f"\n--- {column} ---\n{row[column]}")


def read_random(
    vote: pd.DataFrame, relevance: str | None = None, outlet: str | None = None
) -> None:
    """Print one random article of `vote`, narrowed by label and/or outlet code."""
    pool = vote
    if relevance is not None:
        pool = pool[pool["relevance"] == relevance]
    if outlet is not None:
        pool = pool[pool["medium_code"] == outlet]
    if pool.empty:
        print("no article matches")
        return
    show(vote, int(pool.sample(1).index[0]))  # a fresh RangeIndex: label == position
