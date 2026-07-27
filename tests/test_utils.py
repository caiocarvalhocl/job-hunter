from utils import detect_language, matches_keywords
from scrapers.base import RawJob


def _job(**kw):
    base = dict(source="x", url="https://x.com/1", title="t")
    base.update(kw)
    return RawJob(**base)


class TestMatchesKeywords:
    def test_whole_word_match(self):
        assert matches_keywords(["Java"], "Java Backend Developer")

    def test_java_does_not_match_javascript(self):
        # The original substring bug: "java" in "javascript" == True.
        assert not matches_keywords(["Java"], "Senior JavaScript Engineer")

    def test_multiword_phrase(self):
        assert matches_keywords(["Spring Boot"], "We use Spring Boot in production")

    def test_multiword_phrase_requires_all_tokens(self):
        assert not matches_keywords(["Spring Boot"], "We use Spring Framework only")

    def test_case_insensitive(self):
        assert matches_keywords(["backend developer"], "BACKEND DEVELOPER role")

    def test_searches_across_multiple_texts(self):
        assert matches_keywords(["Java"], "Copywriter", "Requires Java experience")

    def test_no_match_returns_false(self):
        assert not matches_keywords(["Java", "Spring Boot"], "Security Guard")

    def test_empty_keywords_matches_nothing(self):
        assert not matches_keywords([], "Java everywhere")


class TestDetectLanguage:
    def test_gupy_source_is_pt(self):
        assert detect_language(_job(source="gupy")) == "pt"

    def test_brazil_location_is_pt(self):
        assert detect_language(_job(location="São Paulo, Brasil")) == "pt"

    def test_default_is_en(self):
        assert detect_language(_job(source="remotive", location="Anywhere")) == "en"

PT_DESCRIPTION = (
    "Buscamos pessoa desenvolvedora para atuar em nossa equipe. Requisitos: "
    "experiência com Java e conhecimento em SQL. Você vai trabalhar no "
    "desenvolvimento de sistemas. Benefícios: plano de saúde e vale refeição."
)

EN_DESCRIPTION = (
    "We are looking for a developer to join our team. Requirements: "
    "experience with Java and SQL skills. You will work on the development "
    "of our platform. This role is open to candidates based in Brazil."
)


class TestLanguageFollowsPostingText:
    def test_english_posting_on_brazilian_board_gets_english(self):
        job = _job(source="gupy", location="Remoto", description=EN_DESCRIPTION)
        assert detect_language(job) == "en"

    def test_english_posting_restricted_to_brazil_gets_english(self):
        job = _job(source="himalayas", location="Brazil", description=EN_DESCRIPTION)
        assert detect_language(job) == "en"

    def test_portuguese_posting_on_international_board_gets_portuguese(self):
        job = _job(source="remotive", location="LATAM", description=PT_DESCRIPTION)
        assert detect_language(job) == "pt"

    def test_short_text_falls_back_to_source_signal(self):
        assert detect_language(_job(source="gupy", title="Backend Developer")) == "pt"
        assert detect_language(_job(source="remotive", title="Desenvolvedor")) == "en"

