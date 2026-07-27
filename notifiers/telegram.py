from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
import json
import re
from db.models import Job
from config.settings import get_settings
from documents.renderer import text_to_docx, cv_to_docx

settings = get_settings()


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (text or "vaga")).strip("_") or "vaga"


def _escape(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


async def notify_new_job(job: Job) -> bool:
    bot = Bot(token=settings.telegram_bot_token)

    score_emoji = (
        "🟢" if job.fit_score >= 80
        else "🟡" if job.fit_score >= 60
        else "🔴"
    )

    remote_tag = "🌐 Remoto" if job.is_remote else f"📍 {job.location}"

    level_labels = {
        "estagio": "🎓 Estágio/Trainee",
        "junior": "🌱 Júnior",
        "pleno": "🌿 Pleno",
    }
    level_line = level_labels.get(getattr(job, "seniority", None) or "", "")

    message = (
        f"{score_emoji} *Nova vaga encontrada\\!*\n\n"
        f"*{_escape(job.title)}*\n"
        f"🏢 {_escape(job.company or 'Empresa não informada')}\n"
        f"{remote_tag}\n"
        + (f"{_escape(level_line)}\n" if level_line else "")
        + f"📊 Score de fit: *{job.fit_score:.0f}/100*\n\n"
        f"📝 {_escape(job.fit_summary or '')}\n\n"
        f"🔗 [Ver vaga]({job.url})\n"
        f"⚙️ Gerar docs: `/cv {job.id[:8]}` · `/cover {job.id[:8]}` · `/docs {job.id[:8]}`"
    )

    try:
        await bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=False,
        )

        return True

    except TelegramError as e:
        print(f"[TELEGRAM] Error sending notification: {e}")
        return False


async def send_job_documents(job: Job) -> bool:
    """Send whichever documents the job currently has (cover letter, CV)."""
    bot = Bot(token=settings.telegram_bot_token)
    slug = _slug(job.company)

    try:
        if job.cover_letter:
            preview = job.cover_letter[:280].rsplit(" ", 1)[0] + "..."
            doc = text_to_docx(
                f"Cover Letter — {job.title}", job.cover_letter,
                filename=f"cover_letter_{slug}.docx",
            )
            await bot.send_document(
                chat_id=settings.telegram_chat_id,
                document=doc,
                filename=doc.name,
                caption=f"📄 Cover letter — {job.company or ''}\n\n{preview}",
            )

        if job.tailored_cv:
            cv_data = json.loads(job.tailored_cv)
            cv_doc = cv_to_docx(cv_data, filename=f"cv_{slug}.docx")
            await bot.send_document(
                chat_id=settings.telegram_chat_id,
                document=cv_doc,
                filename=cv_doc.name,
                caption=f"🎯 CV adaptado para {job.company or 'esta vaga'}",
            )

        return True

    except TelegramError as e:
        print(f"[TELEGRAM] Error sending documents: {e}")
        return False


async def notify_run_summary(total: int, new: int, notified: int):
    bot = Bot(token=settings.telegram_bot_token)
    message = (
        f"🤖 *Job Hunter — Run concluído*\n\n"
        f"🔍 Vagas analisadas: {total}\n"
        f"✨ Novas vagas: {new}\n"
        f"📬 Notificações enviadas: {notified}"
    )
    try:
        await bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except TelegramError as e:
        print(f"[TELEGRAM] Error sending summary: {e}")
