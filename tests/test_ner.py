from mediapos.ner import align, chunks, fill_repeats, table_lines, untag


def test_chunks_cover_the_text_and_respect_the_limit():
    text = "Eins zwei drei. Vier fünf sechs. Sieben acht neun."
    spans = chunks(text, 4)
    assert all(len(text[s:e].split()) <= 4 for s, e in spans)
    assert " ".join(text[s:e] for s, e in spans) == text


def test_chunks_cut_at_a_sentence_end_when_there_is_one():
    text = "Eins zwei. Drei vier fünf"
    assert text[slice(*chunks(text, 3)[0])] == "Eins zwei."


def test_untag_gives_positions_in_the_plain_text():
    plain, spans = untag('Die <e id="O1">SVP</e> und <e id="P1">Blocher</e>.')
    assert plain == "Die SVP und Blocher."
    assert [(plain[s:e], i) for s, e, i in spans] == [("SVP", "O1"), ("Blocher", "P1")]


def test_align_maps_tags_past_an_added_word():
    piece = "Die SVP verliert."
    plain, spans = untag('Die neue <e id="O1">SVP</e> verliert.')
    kept, dropped, gaps = align(piece, plain, spans)
    assert [piece[s:e] for s, e, _ in kept] == ["SVP"]
    assert dropped == 0
    assert gaps == []


def test_align_drops_a_tag_whose_text_was_edited():
    piece = "Der Bundesrats entschied."
    plain, spans = untag('Der <e id="O1">Bundesrat</e> entschied.')
    kept, dropped, _ = align(piece, plain, spans)
    assert kept == [(4, 13, "O1")]
    assert dropped == 0
    kept, dropped, _ = align("Der Rat entschied.", plain, spans)
    assert kept == []
    assert dropped == 1


def test_align_reports_a_skipped_passage_as_a_whole_word_gap():
    piece = "Titel hier\nDie SVP verliert."
    plain, spans = untag('Die <e id="O1">SVP</e> verliert.')
    kept, _, gaps = align(piece, plain, spans)
    assert [piece[s:e] for s, e, _ in kept] == ["SVP"]
    assert [piece[a:z] for a, z in gaps] == ["Titel hier"]


def test_fill_repeats_fills_untagged_repeats_longest_form_first():
    text = "Tiana Moser sprach. Moser ging. Tiana Moser kam. Mosers Hund."
    spans = [(0, 11, "P1"), (20, 25, "P1")]
    filled = fill_repeats(text, spans)
    assert [text[s:e] for s, e, _ in filled] == ["Tiana Moser"]


def test_table_lines_orders_ids_numerically():
    assert table_lines({}) == "(none yet)"
    assert table_lines({"P10": "a", "P2": "b", "O1": "c"}) == "O1 = c\nP2 = b\nP10 = a"
