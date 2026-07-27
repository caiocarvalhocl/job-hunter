from sqlalchemy import create_engine, Column, String, Integer, Float, Text, DateTime, Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import uuid

from config.settings import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=True)
    url = Column(String, nullable=False, unique=True)
    title = Column(String, nullable=False)
    company = Column(String, nullable=True)
    location = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    salary = Column(String, nullable=True)
    is_remote = Column(Boolean, default=False)
    seniority = Column(String, nullable=True)  # estagio | junior | pleno | senior | unknown

    fit_score = Column(Float, nullable=True)
    fit_summary = Column(Text, nullable=True)
    cover_letter = Column(Text, nullable=True)
    tailored_cv = Column(Text, nullable=True)  # resolved CV dict as JSON

    status = Column(String, default="new")  # new | notified | applied | rejected | ignored

    found_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notified_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Job {self.title} @ {self.company} [{self.source}] score={self.fit_score}>"


def _migrate_sqlite():
    """Additive, idempotent migration for pre-existing SQLite databases.

    create_all() only creates missing tables; it never alters existing ones,
    so new columns must be added by hand for anyone with an old job_hunter.db.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("jobs")}
    if "seniority" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN seniority VARCHAR"))
        print("🛠️  Migration: added jobs.seniority column")


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
    print("✅ Database initialized")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
