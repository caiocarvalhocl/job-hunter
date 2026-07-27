"""Tests for the per-track geographic policy: dev anywhere, QA/support abroad only."""
import pytest

from scrapers.base import RawJob
from filters.track_filter import (
    detect_track, is_brazil_located, is_track_location_allowed,
)
from config.settings import get_settings


@pytest.fixture
def track_rules(monkeypatch):
    """Set TRACK_RULES for one test and restore the cached settings after."""
    def _set(value):
        monkeypatch.setenv("TRACK_RULES", value)
        get_settings.cache_clear()
    yield _set
    get_settings.cache_clear()


def _job(title="", description="", location="", source="remotive", url="https://x.com/1"):
    return RawJob(source=source, url=url, title=title,
                  description=description, location=location)


# ── Track detection ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("Desenvolvedor Java Júnior", "dev"),
    ("Backend Developer", "dev"),
    ("Software Engineer", "dev"),
    ("Fullstack Developer", "dev"),
    ("QA Automation Engineer", "qa"),
    ("Analista de Testes", "qa"),
    ("SDET", "qa"),
    ("Technical Support Engineer", "support"),
    ("Suporte Técnico N2", "support"),
    ("Help Desk Analyst", "support"),
    ("Gerente de Vendas", "unknown"),
])
def test_detect_track(title, expected):
    assert detect_track(_job(title=title)) == expected


def test_dev_wins_over_qa_on_mixed_title():
    # "Developer in Test" mentions both; dev is safe to allow anywhere.
    assert detect_track(_job(title="Software Developer in Test")) == "dev"


# ── Brazil-location detection ────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs", [
    dict(source="gupy"),
    dict(location="São Paulo, SP"),
    dict(location="Remoto - Brasil"),
    dict(location="Curitiba, PR"),
    dict(description="This role is based in Brazil.", location="Remote"),
])
def test_brazil_located_true(kwargs):
    assert is_brazil_located(_job(**kwargs))


@pytest.mark.parametrize("kwargs", [
    dict(source="remotive", location="Worldwide"),
    dict(source="jobicy", location="Anywhere"),
    dict(location="Lisbon, Portugal"),
    dict(location="Remote - US"),
])
def test_brazil_located_false(kwargs):
    assert not is_brazil_located(_job(**kwargs))


# ── Combined policy ──────────────────────────────────────────────────────────

def test_dev_in_brazil_is_allowed():
    ok, _ = is_track_location_allowed(
        _job(title="Desenvolvedor Java Júnior", source="gupy", location="São Paulo"))
    assert ok


def test_dev_abroad_is_allowed():
    ok, _ = is_track_location_allowed(
        _job(title="Backend Developer", location="Worldwide"))
    assert ok


def test_qa_in_brazil_is_blocked():
    ok, reason = is_track_location_allowed(
        _job(title="QA Automation Engineer", source="gupy", location="Remoto - Brasil"))
    assert not ok and "qa" in reason.lower()


def test_qa_abroad_is_allowed():
    ok, _ = is_track_location_allowed(
        _job(title="QA Automation Engineer", source="remotive", location="Worldwide"))
    assert ok


def test_support_in_brazil_is_blocked():
    ok, reason = is_track_location_allowed(
        _job(title="Suporte Técnico N2", source="gupy", location="Curitiba"))
    assert not ok and "support" in reason.lower()


def test_support_abroad_is_allowed():
    ok, _ = is_track_location_allowed(
        _job(title="Technical Support Engineer", location="Remote - Europe"))
    assert ok


def test_unknown_track_is_allowed_anywhere():
    # Don't silently drop unclassified postings; let AI scoring judge them.
    ok, _ = is_track_location_allowed(_job(title="Analyst", source="gupy"))
    assert ok


# ── Config-driven track_rules (TRACK_RULES env var) ─────────────────────────

def test_track_rules_can_open_qa_to_brazil(track_rules):
    track_rules("dev:anywhere,qa:anywhere,support:abroad_only")
    ok, _ = is_track_location_allowed(
        _job(title="QA Automation Engineer", source="gupy", location="Remoto - Brasil"))
    assert ok


def test_track_rules_can_restrict_dev_to_domestic_only(track_rules):
    track_rules("dev:domestic_only,qa:abroad_only,support:abroad_only")
    ok, reason = is_track_location_allowed(
        _job(title="Backend Developer", source="remotive", location="Worldwide"))
    assert not ok and "dev" in reason.lower()


def test_track_rules_unlisted_track_defaults_to_anywhere(track_rules):
    # Only dev is listed; qa/support fall back to "anywhere".
    track_rules("dev:anywhere")
    ok, _ = is_track_location_allowed(
        _job(title="Suporte Técnico N2", source="gupy", location="Curitiba"))
    assert ok
