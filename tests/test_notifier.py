from notifiers.telegram import _escape, _slug


def test_escape_reserved_markdown_v2_chars():
    assert _escape("a.b-c!") == "a\\.b\\-c\\!"


def test_escape_leaves_plain_text():
    assert _escape("Backend Developer") == "Backend Developer"


def test_slug_replaces_non_alnum():
    assert _slug("Acme, Inc.") == "Acme_Inc"


def test_slug_empty_falls_back():
    assert _slug("") == "vaga"
    assert _slug(None) == "vaga"
