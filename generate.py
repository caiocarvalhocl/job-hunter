"""Generate application documents (cover letter and/or tailored CV) for a
specific job already stored in the database.

Usage:
    python generate.py <job>                 # both documents
    python generate.py <job> --cover         # cover letter only
    python generate.py <job> --cv            # tailored CV only
    python generate.py <job> --lang en       # force language (default: auto)
    python generate.py <job> --no-telegram   # save PDF locally, don't send
    python generate.py --list [N]            # list recent candidate jobs

<job> can be:
    - the short id shown in the Telegram notification (first 8+ chars)
    - the full job UUID
    - the job URL
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from db.models import init_db, SessionLocal, Job
from scrapers.base import RawJob
from generators.cover_letter import generate_cover_letter
from generators.tailored_cv import tailor_cv
from documents.renderer import text_to_pdf, cv_to_pdf
from notifiers.telegram import send_job_documents, _slug, _candidate_slug

OUTPUT_DIR = Path("output")


class Ambiguous(Exception):
    def __init__(self, matches):
        self.matches = matches


def resolve_job(db: Session, ref: str) -> Job:
    """Find a job by URL, full id, or unique id prefix (min 6 chars)."""
    ref = ref.strip()

    if ref.startswith("http"):
        job = db.query(Job).filter(Job.url == ref).first()
        if job:
            return job
        raise LookupError(f"Nenhuma vaga com a URL {ref}")

    job = db.query(Job).filter(Job.id == ref).first()
    if job:
        return job

    if len(ref) < 6:
        raise LookupError("Use pelo menos 6 caracteres do id (ou a URL completa).")

    matches = db.query(Job).filter(Job.id.like(f"{ref}%")).all()
    if not matches:
        raise LookupError(f"Nenhuma vaga com id começando em '{ref}'.")
    if len(matches) > 1:
        raise Ambiguous(matches)
    return matches[0]


def raw_from_job(job: Job) -> RawJob:
    return RawJob(
        source=job.source,
        url=job.url,
        title=job.title,
        company=job.company or "",
        location=job.location or "",
        description=job.description or "",
        salary=job.salary or "",
        is_remote=bool(job.is_remote),
        external_id=job.external_id or "",
    )


def _save_pdf(doc, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = doc.getvalue() if hasattr(doc, "getvalue") else doc.read()
    path.write_bytes(data)
    return path


def list_jobs(db: Session, n: int):
    jobs = (
        db.query(Job)
        .filter(Job.status.in_(["new", "notified", "applied"]))
        .order_by(Job.fit_score.desc().nullslast())
        .limit(n)
        .all()
    )
    if not jobs:
        print("Nenhuma vaga candidata no banco ainda.")
        return
    print(f"{'ID':<10}{'SCORE':<7}{'NÍVEL':<9}{'DOCS':<6}TÍTULO — EMPRESA")
    for j in jobs:
        docs = ("C" if j.cover_letter else "-") + ("V" if j.tailored_cv else "-")
        score = f"{j.fit_score:.0f}" if j.fit_score is not None else "?"
        level = j.seniority or "?"
        print(f"{j.id[:8]:<10}{score:<7}{level:<9}{docs:<6}{j.title} — {j.company or '?'}")


async def generate(job: Job, db: Session, want_cover: bool, want_cv: bool,
                   lang: str, send: bool):
    raw = raw_from_job(job)
    if not job.description:
        print("⚠️  Vaga sem descrição no banco; os documentos sairão menos "
              "personalizados (só título/empresa disponíveis).")

    if want_cover:
        print(f"✍️  Gerando cover letter ({lang})...")
        job.cover_letter = await generate_cover_letter(raw, language=lang)

    if want_cv:
        print(f"🎯 Adaptando CV ({lang})...")
        resolved = await tailor_cv(raw, lang=None if lang == "auto" else lang)
        job.tailored_cv = json.dumps(resolved, ensure_ascii=False)

    db.commit()

    slug = _slug(job.company)
    name = _candidate_slug()
    saved = []
    if job.cover_letter and want_cover:
        doc = text_to_pdf(f"Cover Letter — {job.title}", job.cover_letter,
                          filename=f"{name}_cover_letter_{slug}.pdf")
        saved.append(_save_pdf(doc, OUTPUT_DIR / f"{name}_cover_letter_{slug}_{job.id[:8]}.pdf"))
    if job.tailored_cv and want_cv:
        doc = cv_to_pdf(json.loads(job.tailored_cv), filename=f"{name}_cv_{slug}.pdf")
        saved.append(_save_pdf(doc, OUTPUT_DIR / f"{name}_cv_{slug}_{job.id[:8]}.pdf"))

    for path in saved:
        print(f"💾 {path}")

    if send:
        snapshot_cover, snapshot_cv = job.cover_letter, job.tailored_cv
        if not want_cover:
            job.cover_letter = None
        if not want_cv:
            job.tailored_cv = None
        ok = await send_job_documents(job)
        job.cover_letter, job.tailored_cv = snapshot_cover, snapshot_cv
        print("📬 Enviado no Telegram" if ok else "⚠️  Falha ao enviar no Telegram")


def main():
    parser = argparse.ArgumentParser(
        description="Gera cover letter e/ou CV para uma vaga do banco.")
    parser.add_argument("job", nargs="?", help="id curto, UUID ou URL da vaga")
    parser.add_argument("--cover", action="store_true", help="gerar só a cover letter")
    parser.add_argument("--cv", action="store_true", help="gerar só o CV")
    parser.add_argument("--lang", choices=["auto", "pt", "en"], default="auto",
                        help="idioma dos documentos (padrão: detectar pela vaga)")
    parser.add_argument("--no-telegram", action="store_true",
                        help="não enviar pelo Telegram, só salvar em output/")
    parser.add_argument("--list", nargs="?", const=15, type=int, metavar="N",
                        help="listar as N melhores vagas candidatas (padrão 15)")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.list is not None:
            list_jobs(db, args.list)
            return
        if not args.job:
            parser.error("informe o id/URL da vaga ou use --list")

        try:
            job = resolve_job(db, args.job)
        except Ambiguous as e:
            print("Id ambíguo; candidatos:")
            for j in e.matches:
                print(f"  {j.id[:12]}  {j.title} — {j.company or '?'}")
            sys.exit(1)
        except LookupError as e:
            print(str(e))
            sys.exit(1)

        want_cover = args.cover or not (args.cover or args.cv)
        want_cv = args.cv or not (args.cover or args.cv)

        header = f"📌 {job.title} — {job.company or '?'}"
        if job.fit_score is not None:
            header += f" (score {job.fit_score:.0f})"
        print(header)
        asyncio.run(generate(job, db, want_cover, want_cv,
                             args.lang, send=not args.no_telegram))
    finally:
        db.close()


if __name__ == "__main__":
    main()
