"""Tests for /run (forced run) and /log (proof the models are answering).

Sem rede: as chamadas aos providers são substituídas por fakes; o que se
verifica é a telemetria gravada por llm.chat e o texto que o /log monta.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import bot
import llm
import main as pipeline
from bot import build_application, format_llm_log, cmd_run, cmd_log
from db.models import LLMCall


def _rate_limit_error():
    import httpx
    from groq import RateLimitError
    req = httpx.Request("POST", "https://api.groq.com/x")
    return RateLimitError("rate limited", response=httpx.Response(429, request=req), body=None)


@pytest.fixture
def fake_update():
    sent = []

    async def reply_text(text, **kw):
        sent.append(text)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=bot.settings.telegram_chat_id),
        message=SimpleNamespace(text="/log", reply_text=reply_text),
    )
    return update, sent


# ── telemetria em llm.chat ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_records_successful_groq_call(db_session, monkeypatch):
    async def fake_groq(prompt, max_tokens, temperature):
        return llm._Completion("ok", "openai/gpt-oss-120b", 120, 30)

    monkeypatch.setattr(llm, "_chat_groq", fake_groq)
    assert await llm.chat("oi", context="FILTER") == "ok"

    (call,) = db_session.query(LLMCall).all()
    assert (call.provider, call.model, call.context, call.ok) == (
        "groq", llm.GROQ_MODEL, "FILTER", True)
    assert (call.prompt_tokens, call.completion_tokens, call.output_chars) == (120, 30, 2)
    assert call.served_model == "openai/gpt-oss-120b"


@pytest.mark.asyncio
async def test_rate_limit_is_logged_then_fallback_is_logged(db_session, monkeypatch):
    async def groq_429(prompt, max_tokens, temperature):
        raise _rate_limit_error()

    async def claude_ok(prompt, max_tokens, temperature):
        return llm._Completion("resposta", "claude-haiku-4-5", 10, 5)

    monkeypatch.setattr(llm, "_chat_groq", groq_429)
    monkeypatch.setattr(llm, "_chat_claude", claude_ok)
    monkeypatch.setattr(llm, "_fallback_enabled", lambda: True)

    assert await llm.chat("oi", context="FILTER") == "resposta"

    calls = db_session.query(LLMCall).order_by(LLMCall.id).all()
    assert [(c.provider, c.ok) for c in calls] == [("groq", False), ("anthropic", True)]
    assert "RateLimitError" in calls[0].error


@pytest.mark.asyncio
async def test_telemetry_failure_never_breaks_the_call(monkeypatch):
    async def fake_groq(prompt, max_tokens, temperature):
        return llm._Completion("ok")

    def broken_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(llm, "_chat_groq", fake_groq)
    monkeypatch.setattr(llm, "SessionLocal", broken_session)
    assert await llm.chat("oi") == "ok"


# ── /log ─────────────────────────────────────────────────────────────────────

def test_log_without_calls_explains_why(db_session):
    text = format_llm_log(db_session)
    assert "Nenhuma chamada" in text
    assert llm.GROQ_MODEL in text


def test_log_lists_models_failures_and_empty_responses(db_session, monkeypatch):
    monkeypatch.setattr(llm, "_fallback_enabled", lambda: True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add_all([
        LLMCall(provider="groq", model=llm.GROQ_MODEL, served_model=llm.GROQ_MODEL,
                context="FILTER", ok=True, latency_ms=1800, prompt_tokens=800,
                completion_tokens=90, output_chars=200, ts=now - timedelta(minutes=3)),
        LLMCall(provider="groq", model=llm.GROQ_MODEL, context="FILTER", ok=False,
                error="RateLimitError: 429", ts=now - timedelta(minutes=2)),
        LLMCall(provider="anthropic", model=llm.CLAUDE_FALLBACK_MODEL, context="FILTER",
                ok=True, latency_ms=900, prompt_tokens=800, completion_tokens=0,
                output_chars=0, ts=now - timedelta(minutes=1)),
        LLMCall(provider="groq", model=llm.GROQ_MODEL, context="OLD", ok=True,
                latency_ms=100, output_chars=5, ts=now - timedelta(hours=30)),
    ])
    db_session.commit()

    text = format_llm_log(db_session, 10)

    assert "anthropic/claude-haiku-4-5" in text     # fallback configurado/usado
    assert "1 falha(s)" in text                     # falha aparece no resumo 24h
    assert "❌" in text and "RateLimitError" in text
    assert "resposta vazia" in text                 # 'ok' com 0 chars é sinalizado
    assert "OLD" in text                            # recentes incluem a antiga
    # ...mas o resumo de 24h ignora a chamada de 30h atrás
    assert "2 ok" not in text.split("Últimas 24h:")[1].split("Última chamada")[0]


def test_log_clamps_line_count(db_session):
    db_session.add_all([LLMCall(provider="groq", model="m", ok=True, output_chars=1)
                        for _ in range(45)])
    db_session.commit()
    body = format_llm_log(db_session, 999).split("Chamadas mais recentes")[-1]
    assert body.count("✅") == bot.LOG_MAX_LINES


@pytest.mark.asyncio
async def test_cmd_log_parses_count_and_replies(db_session, fake_update):
    update, sent = fake_update
    update.message.text = "/log 5"
    await cmd_log(update, None)
    assert len(sent) == 1 and "modelos" in sent[0]


@pytest.mark.asyncio
async def test_commands_ignore_other_chats(db_session, fake_update):
    update, sent = fake_update
    update.effective_chat.id = "999999"
    await cmd_log(update, None)
    await cmd_run(update, None)
    assert sent == []


# ── /run ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_starts_in_background_and_reports_llm_usage(db_session, fake_update, monkeypatch):
    update, sent = fake_update

    async def fake_run():
        db_session.add(LLMCall(provider="groq", model=llm.GROQ_MODEL, ok=True,
                               latency_ms=1000, prompt_tokens=10, completion_tokens=5,
                               output_chars=9, ts=datetime.now(timezone.utc).replace(tzinfo=None)))
        db_session.commit()
        return {"found": 7, "new": 3, "notified": 1}

    monkeypatch.setattr(pipeline, "run", fake_run)
    await cmd_run(update, None)
    assert "iniciada" in sent[0]
    await asyncio.gather(*list(bot._background_runs))

    assert "7 encontradas, 3 novas, 1 notificadas" in sent[-1]
    assert f"groq/{llm.GROQ_MODEL.split('/')[-1]}: 1 ok" in sent[-1]


@pytest.mark.asyncio
async def test_run_reports_failure(db_session, fake_update, monkeypatch):
    update, sent = fake_update

    async def boom():
        raise RuntimeError("scraper explodiu")

    monkeypatch.setattr(pipeline, "run", boom)
    await cmd_run(update, None)
    await asyncio.gather(*list(bot._background_runs))
    assert "falhou" in sent[-1] and "scraper explodiu" in sent[-1]


@pytest.mark.asyncio
async def test_run_refuses_when_a_run_is_already_in_progress(db_session, fake_update):
    update, sent = fake_update
    async with pipeline._run_lock:
        await cmd_run(update, None)
        assert await pipeline.run() is None   # scheduler disparando junto também é descartado
    assert "em andamento" in sent[0]
    assert not bot._background_runs


@pytest.mark.asyncio
async def test_pipeline_run_returns_totals(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(pipeline, "get_all_scrapers", lambda: [])
    monkeypatch.setattr(pipeline, "notify_run_summary", none)
    assert await pipeline.run() == {"found": 0, "new": 0, "notified": 0}
    assert not pipeline.is_running()


def test_new_commands_are_registered():
    app = build_application()
    commands = {c for h in app.handlers[0] for c in h.commands}
    assert {"run", "log"} <= commands
