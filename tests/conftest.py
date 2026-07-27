"""Shared test setup: dummy env vars and repo root on sys.path.

Settings require GROQ/Telegram vars; tests never hit the network, but some
modules read config at import time, so we provide inert placeholders.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "0")

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest  # noqa: E402


# ── Fatos derivados do perfil carregado ─────────────────────────────────────
# Vários testes precisam de "uma skill real", "uma empresa real". Fixar
# "Java" ou "CISS S.A." faria a suíte falhar em qualquer fork cujo
# master_profile.yaml seja diferente, o que é exatamente o cenário deste
# projeto (cada pessoa com o próprio perfil). Estas fixtures leem o perfil
# em uso e devolvem um exemplo real dele.

@pytest.fixture
def profile():
    from profile import load_profile
    return load_profile()


@pytest.fixture
def a_real_skill(profile):
    for group in profile["skills"].values():
        for skill in group:
            return skill
    pytest.skip("perfil sem nenhuma skill cadastrada")


@pytest.fixture
def a_real_experience(profile):
    if not profile.get("experience"):
        pytest.skip("perfil sem nenhuma experiência cadastrada")
    return profile["experience"][0]


@pytest.fixture
def db_session():
    """Fresh in-memory schema per test."""
    from db.models import Base, engine, SessionLocal

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
