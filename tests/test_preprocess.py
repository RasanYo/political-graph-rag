import pandas as pd

from mediapos.preprocess import keep_longest, select_vote, split_content, to_text


def test_inline_tags_do_not_fuse_words():
    assert to_text('einen<a href="x">Bausatz</a> kaufen') == "einen Bausatz kaufen"


def test_block_tags_become_lines():
    assert to_text("<p>eins</p><p>zwei</p>") == "eins\nzwei"


def test_entities_are_unescaped():
    assert to_text("<p>A &amp; B</p>") == "A & B"


def test_bylines_and_credits_are_dropped_and_side_columns_kept_apart():
    markup = (
        "<au>Anna Autorin</au><p>Text.</p>"
        "<lg>Ein Bild <ur>Foto: Keystone</ur></lg><ka>Zitat</ka><nt>Notiz</nt>"
    )
    parts = split_content(markup)
    assert parts == {
        "captions": "Ein Bild",
        "boxes": "Zitat",
        "notes": "Notiz",
        "body": "Text.",
    }


def test_keep_longest_keeps_one_row_per_id_with_a_stable_tie_break():
    articles = pd.DataFrame(
        {
            "id": ["1", "1", "2", "2"],
            "char_count": [10, 20, 5, 5],
            "content_id": ["a", "b", "d", "c"],
        }
    )
    kept = keep_longest(articles)
    assert kept["content_id"].tolist() == ["b", "c"]


def test_select_vote_counts_any_case_and_flags_the_headline():
    articles = pd.DataFrame(
        {
            "head": ["BEGRENZUNGSINITIATIVE abgelehnt", "Wetter"],
            "subhead": ["", ""],
            "content": [
                "Die Kündigungs-Initiative und die Begrenzungsinitiative",
                "Sonne",
            ],
        }
    )
    vote = select_vote(articles)
    assert len(vote) == 1
    assert vote.loc[0, "n_vote_mentions"] == 3
    assert bool(vote.loc[0, "vote_in_head"])
