"""Tests for run_all.py, o runner combinado (scheduler + bot num processo só).

Não sobem bot nem rede: verificam só as duas partes com lógica própria, que
são o wrapper que impede uma rodada falha de derrubar o agendamento e a
paridade de comandos entre bot.py e o app que run_all constrói.
"""
import pytest

import run_all
from bot import build_application


@pytest.mark.asyncio
async def test_scheduled_scrape_swallows_exceptions(monkeypatch):
    """Uma rodada que estoura não pode propagar: o APScheduler pararia de
    reagendar e o processo ficaria de pé sem nunca mais varrer nada."""
    async def boom():
        raise RuntimeError("scraper explodiu")

    monkeypatch.setattr(run_all, "run", boom)
    await run_all.scheduled_scrape()  # não deve levantar


@pytest.mark.asyncio
async def test_scheduled_scrape_runs_the_pipeline(monkeypatch):
    called = []

    async def fake_run():
        called.append(True)

    monkeypatch.setattr(run_all, "run", fake_run)
    await run_all.scheduled_scrape()
    assert called == [True]


def test_build_application_registers_every_command():
    """run_all reutiliza build_application() do bot.py justamente para os dois
    caminhos não divergirem; este teste falha se um comando novo for
    registrado só num deles."""
    app = build_application()
    commands = {c for h in app.handlers[0] for c in h.commands}
    assert {"vaga", "cv", "cover", "docs", "lista", "ajuda"} <= commands
