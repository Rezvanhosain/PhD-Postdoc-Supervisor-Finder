from proposal_engine.sources.openalex import _normalize, reconstruct_abstract


def test_reconstruct_abstract_orders_words():
    inv = {"Hello": [0], "world": [1], "again": [2]}
    assert reconstruct_abstract(inv) == "Hello world again"


def test_reconstruct_abstract_handles_repeats():
    inv = {"the": [0, 2], "cat": [1], "sat": [3]}
    assert reconstruct_abstract(inv) == "the cat the sat"


def test_reconstruct_abstract_empty():
    assert reconstruct_abstract(None) == ""


def test_normalize_openalex_work():
    raw = {
        "display_name": "A Title",
        "publication_year": 2021,
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {"source": {"display_name": "Nature"}},
        "doi": "https://doi.org/10.1/xyz",
        "abstract_inverted_index": {"Great": [0], "work": [1]},
        "open_access": {"oa_url": "http://oa/x.pdf"},
        "cited_by_count": 42,
        "id": "https://openalex.org/W1",
    }
    n = _normalize(raw)
    assert n["title"] == "A Title"
    assert n["doi"] == "10.1/xyz"
    assert n["abstract"] == "Great work"
    assert n["authors"] == ["Ada Lovelace"]
    assert n["oa_url"] == "http://oa/x.pdf"
    assert n["source_api"] == "openalex"
