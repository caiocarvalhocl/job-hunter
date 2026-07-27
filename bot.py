"""Long-running Telegram bot: listens for commands, doesn't scrape anything
on its own.

Run separately from the scraping pipeline (main.py) and the scheduler:

    python bot.py

Commands:
    /vaga <url>              — fetch that one page once, score it, save it
    /vaga <url>\\n<texto>     — same, but use the pasted text instead of
                                fetching (zero automated access; use this for
                                LinkedIn postings behind a login wall)
    /ajuda                   — show this help

Only messages from TELEGRAM_CHAT_ID are processed; everyone else is ignored,
since this is a personal assistant, not a public bot.
"""
import json
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config.settings import get_settings
from db.models import init_db, SessionLocal, Job
from scrapers.base import RawJob
from scrapers.single_fetch import fetch_posting
from filters.seniority_filter import detect_level, is_above_target
from filters.location_filter import is_pcd_reserved
from filters.track_filter import is_track_location_allowed
from filters.ai_filter import score_job_fit
from utils import detect_language
from generate import resolve_job, raw_from_job, Ambiguous
from generators.cover_letter import generate_cover_letter
from generators.tailored_cv import tailor_cv
from notifiers.telegram import send_job_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("bot")

settings = get_settings()

HELP_TEXT = (
    "🤖 *Comandos*\n\n"
    "`/vaga <url>` — busca a página uma vez, pontua e salva a vaga\\.\n"
    "`/vaga <url>` seguido de uma nova linha com o texto da descrição — "
    "usa o texto colado em vez de buscar a página \\(recomendado para "
    "LinkedIn, evita qualquer acesso automatizado\\)\\.\n\n"
    "Depois de salvar, gere os documentos aqui mesmo, sem terminal:\n"
    "`/cv <id>` — gera e envia o CV adaptado\\.\n"
    "`/cover <id>` — gera e envia a cover letter \\(`/resume` é atalho\\)\\.\n"
    "`/docs <id>` — gera e envia os dois\\.\n"
    "Acrescente `en` ou `pt` para forçar o idioma \\(ex\\.: `/cv a1b2c3d4 en`\\)\\.\n\n"
    "`/lista` — mostra as vagas candidatas com seus ids\\."
)


def _authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(settings.telegram_chat_id)


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="MarkdownV2")


def parse_vaga_command(body: str) -> tuple[str, str]:
    """Split '/vaga <url>\\n<description>' into (url, description).

    Pure function so it's testable without mocking Telegram Update objects.
    Returns ("", "") when body has no URL-looking first line.
    """
    lines = body.strip().split("\n", 1)
    url = lines[0].strip()
    description = lines[1].strip() if len(lines) > 1 else ""
    if not url.startswith("http"):
        return "", ""
    return url, description


async def cmd_vaga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return

    raw_text = update.message.text or ""
    body = raw_text.split(maxsplit=1)[1] if " " in raw_text else ""
    if not body.strip():
        await update.message.reply_text(
            "Uso: `/vaga <url>` \\(opcionalmente seguido do texto da vaga "
            "numa linha abaixo\\)", parse_mode="MarkdownV2")
        return

    url, pasted_description = parse_vaga_command(body)
    if not url:
        await update.message.reply_text("Isso não parece uma URL válida.")
        return

    db = SessionLocal()
    try:
        existing = db.query(Job).filter(Job.url == url).first()
        if existing:
            await update.message.reply_text(
                f"Essa vaga já está no banco (id `{existing.id[:8]}`, "
                f"status: {existing.status}).",
                parse_mode="MarkdownV2",
            )
            return

        if pasted_description:
            title_guess = pasted_description.split("\n", 1)[0][:120]
            raw = RawJob(
                source="linkedin-manual" if "linkedin.com" in url else "manual",
                url=url, title=title_guess, description=pasted_description,
            )
            await update.message.reply_text("📝 Usando o texto colado (sem buscar a página).")
        else:
            await update.message.reply_text("🔎 Buscando a página (uma vez, sem crawling)...")
            fetched = await fetch_posting(url)
            if not fetched.ok:
                await update.message.reply_text(
                    f"⚠️ Não consegui extrair o suficiente da página "
                    f"({fetched.error}). Manda de novo com `/vaga {url}` "
                    f"seguido do texto da vaga colado numa linha abaixo.",
                    parse_mode="MarkdownV2",
                )
                return
            raw = RawJob(
                source="linkedin-manual" if "linkedin.com" in url else "manual",
                url=url, title=fetched.title, company=fetched.company,
                location=fetched.location, description=fetched.description,
                is_remote=fetched.is_remote,
            )

        level = detect_level(raw.title)
        lang = detect_language(raw)

        # PCD is a hard exclusion even for manual adds: applying to a reserved
        # opening you're not eligible for wastes everyone's time. Skipped
        # entirely when this instance turned the filter off
        # (EXCLUDE_PCD_RESERVED=false), i.e. the person running it is PCD.
        if settings.exclude_pcd_reserved and is_pcd_reserved(raw.title, raw.description):
            await update.message.reply_text(
                "🚫 Essa vaga é afirmativa reservada para PCD — não salvando."
            )
            return

        # Track/location policy is only a NOTE here, not a block: a manual add
        # means you already decided you want this job, so a Brazilian QA role
        # you chose on purpose should still be saved.
        note = ""
        track_ok, track_reason = is_track_location_allowed(raw)
        if not track_ok:
            note += f"\n⚠️ {track_reason} (salvando mesmo assim porque você adicionou manualmente)."
        if is_above_target(raw.title, settings.accept_pleno):
            note += f"\n⚠️ Nível detectado: *{level}* (fora do alvo, mas salvando mesmo assim)."

        await update.message.reply_text("🧠 Avaliando fit com a IA...")
        result = await score_job_fit(raw)
        score, summary = result if result else (None, "Scoring indisponível no momento.")

        job = Job(
            source=raw.source, url=raw.url, title=raw.title or "(sem título)",
            company=raw.company, location=raw.location, description=raw.description,
            is_remote=raw.is_remote, seniority=level,
            fit_score=score, fit_summary=summary, status="new",
        )
        db.add(job)
        db.commit()

        score_line = f"{score:.0f}/100" if score is not None else "indisponível"
        await update.message.reply_text(
            f"✅ Salva\\!\n\n"
            f"*{job.title}*\n"
            f"🏢 {job.company or 'não identificada'}\n"
            f"📊 Score: *{score_line}*\n"
            f"📝 {summary}"
            f"{note}\n\n"
            f"⚙️ Gerar aqui: `/cv {job.id[:8]}` · `/cover {job.id[:8]}` · `/docs {job.id[:8]}`",
            parse_mode="Markdown",
        )
    finally:
        db.close()


def _parse_gen_args(text: str) -> tuple[str, str]:
    """Parse '/cv <id> [pt|en]' → (ref, lang). lang defaults to 'auto'."""
    parts = (text or "").split()
    ref = parts[1] if len(parts) > 1 else ""
    lang = "auto"
    if len(parts) > 2 and parts[2].lower() in ("pt", "en"):
        lang = parts[2].lower()
    return ref, lang


async def _generate_and_send(update: Update, want_cover: bool, want_cv: bool):
    ref, lang = _parse_gen_args(update.message.text)
    if not ref:
        await update.message.reply_text(
            "Uso: `/cv <id>` (ou `/cover`, `/docs`). Veja os ids com /lista.",
            parse_mode="Markdown")
        return

    db = SessionLocal()
    try:
        try:
            job = resolve_job(db, ref)
        except Ambiguous as e:
            lines = "\n".join(f"• `{j.id[:8]}` {j.title}" for j in e.matches)
            await update.message.reply_text(
                f"Id ambíguo, escolha:\n{lines}", parse_mode="Markdown")
            return
        except LookupError as e:
            await update.message.reply_text(str(e))
            return

        kind = "CV" if (want_cv and not want_cover) else \
               "cover letter" if (want_cover and not want_cv) else "CV + cover letter"
        await update.message.reply_text(
            f"⏳ Gerando {kind} para *{job.title}* ({lang})...",
            parse_mode="Markdown")

        raw = raw_from_job(job)
        try:
            if want_cover:
                job.cover_letter = await generate_cover_letter(raw, language=lang)
            if want_cv:
                resolved = await tailor_cv(raw, lang=None if lang == "auto" else lang)
                job.tailored_cv = json.dumps(resolved, ensure_ascii=False)
            db.commit()
        except Exception as e:
            log.exception("generation failed")
            await update.message.reply_text(
                f"⚠️ Falha ao gerar (provável rate limit da IA): {e}\n"
                f"Tente de novo em alguns minutos.")
            return

        # Send only what was requested this turn, without losing the other
        # document already stored on the job.
        snapshot_cover, snapshot_cv = job.cover_letter, job.tailored_cv
        if not want_cover:
            job.cover_letter = None
        if not want_cv:
            job.tailored_cv = None
        ok = await send_job_documents(job)
        job.cover_letter, job.tailored_cv = snapshot_cover, snapshot_cv

        await update.message.reply_text(
            "✅ Enviado!" if ok else "⚠️ Gerado, mas falhou ao enviar o arquivo.")
    finally:
        db.close()


async def cmd_cv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _generate_and_send(update, want_cover=False, want_cv=True)


async def cmd_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _generate_and_send(update, want_cover=True, want_cv=False)


async def cmd_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _generate_and_send(update, want_cover=True, want_cv=True)


async def cmd_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        jobs = (
            db.query(Job)
            .filter(Job.status.in_(["new", "notified", "applied"]))
            .order_by(Job.fit_score.desc().nullslast())
            .limit(15)
            .all()
        )
        if not jobs:
            await update.message.reply_text("Nenhuma vaga candidata no banco ainda.")
            return
        lines = []
        for j in jobs:
            docs = ("📄" if j.cover_letter else "") + ("🎯" if j.tailored_cv else "")
            score = f"{j.fit_score:.0f}" if j.fit_score is not None else "?"
            lines.append(f"`{j.id[:8]}` [{score}] {j.title[:45]} {docs}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        db.close()


def register_handlers(app: Application) -> Application:
    """Attach every command handler to an Application.

    Kept separate from main() so run_all.py can build the same bot inside its
    own event loop without duplicating the handler list here and there, which
    is exactly how the two would drift apart over time.
    """
    app.add_handler(CommandHandler("vaga", cmd_vaga))
    app.add_handler(CommandHandler("cv", cmd_cv))
    app.add_handler(CommandHandler(["cover", "resume", "carta"], cmd_cover))
    app.add_handler(CommandHandler("docs", cmd_docs))
    app.add_handler(CommandHandler(["lista", "list"], cmd_lista))
    app.add_handler(CommandHandler(["ajuda", "help", "start"], cmd_ajuda))
    return app


def build_application() -> Application:
    return register_handlers(
        Application.builder().token(settings.telegram_bot_token).build()
    )


def main():
    init_db()
    app = build_application()
    log.info("Bot listening (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
