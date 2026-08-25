from slug import slugify


def test_accents_and_empty_fallback() -> None:
    assert slugify("Crème brûlée") == "creme-brulee"
    assert slugify("---") == "item"
