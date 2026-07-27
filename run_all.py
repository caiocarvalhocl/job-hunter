"""Roda o scheduler e o bot do Telegram no MESMO processo, em um terminal só.

    python run_all.py

Antes existiam dois processos separados (`python scheduler.py` e
`python bot.py`), cada um com seu terminal. Os dois já eram asyncio por
baixo, então dá para hospedar os dois no mesmo event loop: o APScheduler
dispara o scraping de tempos em tempos e o bot fica em long polling, sem um
bloquear o outro, porque todo o pipeline (scrapers, chamadas de LLM, envio
para o Telegram) é await-based e devolve o controle ao loop.

IMPORTANTE: não rode `run_all.py` e `bot.py` ao mesmo tempo. Dois long
pollings com o mesmo token fazem a API do Telegram devolver 409 Conflict e
os dois processos passam a perder mensagens. Escolha um dos dois.

Os arquivos antigos continuam funcionando e não foram removidos:
  - `python scheduler.py` = só o scraping agendado, sem bot.
  - `python bot.py`       = só o bot, sem scraping automático.
  - `python main.py`      = uma única rodada de scraping e sai.
"""
import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import get_settings
from db.models import init_db
from main import run
from bot import build_application

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("run_all")

# O python-telegram-bot loga cada requisição HTTP em INFO, o que polui o
# terminal a ponto de esconder a saída do scraping. WARNING é suficiente.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

settings = get_settings()


async def scheduled_scrape():
    """Wrapper em volta de run() que nunca deixa a exceção subir.

    Se run() estourar e a exceção escapar, o APScheduler marca o job como
    falho e, dependendo da configuração, para de reagendar. Como este
    processo deve ficar de pé por dias, engolir o erro (com log) e esperar
    a próxima janela é preferível a perder o agendamento silenciosamente.
    """
    try:
        await run()
    except Exception:
        log.exception("Rodada de scraping falhou; seguindo para a próxima janela")


async def main():
    init_db()

    app = build_application()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_scrape,
        trigger=IntervalTrigger(hours=settings.scrape_interval_hours),
        id="job_hunter",
        name="Job Hunter Scraper",
        replace_existing=True,
        # Se uma rodada demorar mais que o intervalo, não empilhe duas ao
        # mesmo tempo: pular a atrasada evita rodar dois scrapings em
        # paralelo consumindo cota da LLM em dobro.
        max_instances=1,
        coalesce=True,
    )

    # Ciclo de vida manual do PTB. run_polling() cria e gerencia o próprio
    # event loop, o que é incompatível com hospedar o scheduler junto; a
    # API async explícita (initialize/start/start_polling) permite os dois
    # no mesmo loop.
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    scheduler.start()

    log.info("🤖 Bot ouvindo comandos do Telegram")
    log.info("⏰ Scheduler ativo, rodando a cada %sh", settings.scrape_interval_hours)
    log.info("🔍 Primeira varredura começando agora, em segundo plano")
    log.info("Ctrl+C para encerrar os dois.")

    # A primeira varredura vai para uma task em background de propósito: se
    # fosse await direto, o bot só começaria a responder comandos depois que
    # o scraping inteiro terminasse, o que pode levar minutos.
    first_scan = asyncio.create_task(scheduled_scrape())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows não implementa add_signal_handler; lá o Ctrl+C vira
            # KeyboardInterrupt e é tratado no except lá embaixo.
            pass

    try:
        await stop.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log.info("👋 Encerrando...")
        first_scan.cancel()
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
