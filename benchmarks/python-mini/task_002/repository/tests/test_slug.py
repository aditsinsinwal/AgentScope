from slug import slugify


def test_ascii_slug() -> None:
    assert slugify("Hello, Friendly World!") == "hello-friendly-world"
