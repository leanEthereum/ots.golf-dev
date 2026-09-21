"""Database: users and submissions, in SQLite (WAL) under the data directory."""
from __future__ import annotations

import hashlib

import json
import fcntl
import re
import shlex
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    """Naive UTC, which is what every backend stores faithfully."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stable_id(*parts: str) -> str:
    """A submission id that depends only on what was submitted, so every page link survives
    rebuilding the database from GitHub."""
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def pr_submission_id(pr_repository: str, pr_number: int, commit: str, epoch: str | None = None) -> str:
    from . import contract
    return stable_id("pr", pr_repository.lower(), str(pr_number), commit.lower(),
                     contract.contract_id() if epoch is None else epoch)


def legacy_pr_submission_id(pr_repository: str, pr_number: int, commit: str) -> str:
    return stable_id("pr", pr_repository.lower(), str(pr_number), commit.lower())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    login: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submissions: Mapped[list["Submission"]] = relationship(back_populates="user")



class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    track: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_repo: Mapped[str] = mapped_column(String(400))
    commit: Mapped[str] = mapped_column(String(64))
    claim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    is_record: Mapped[bool] = mapped_column(Boolean, default=False)
    record_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assisted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    co_authors: Mapped[str] = mapped_column(Text, default="[]")
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    log_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    user: Mapped[User] = relationship(back_populates="submissions")

    @property
    def riscv_program_size(self):
        from .riscv_program_size import for_submission
        return for_submission(self)

    @property
    def co_authors_list(self) -> list[str]:
        try:
            value = json.loads(self.co_authors or "[]")
            return [name for name in value if isinstance(name, str)] if isinstance(value, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def detail_dict(self) -> dict:
        try:
            value = json.loads(self.detail or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    @property
    def current_contract(self) -> bool:
        from . import contract, revalidations
        return (self.detail_dict.get("contract") == contract.contract_id()
                or (self.status == "verified"
                    and (contract.compatible_result(self.track, self.detail_dict.get("contract"))
                         or revalidations.for_original(self) is not None)))

    @property
    def notes(self) -> str | None:
        """The submitter's `NOTES.md`, as read by the verifier from the checked head."""
        value = self.detail_dict.get("notes")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def archive_url(self) -> str | None:
        """The immutable snapshot captured before verification, when its object is retained."""
        from . import source_archive
        if self.detail_dict.get("demo") or not source_archive.is_available(self):
            return None
        return f"{settings.base_url}/submissions/{self.id}/source.zip"

    @property
    def source_url(self) -> str | None:
        """Browse the retained, exact submitted root even if the local ZIP cache is absent."""
        from . import github, source_archive
        detail = self.detail_dict
        receipt = detail.get("receipt") or {}
        root = receipt.get("submission_root") if isinstance(receipt, dict) else None
        repo = self.pr_repository
        if (detail.get("demo") or not repo or not github.SHA_RE.fullmatch(self.commit or "")
                or detail.get("source_ref") != f"refs/tags/ots-source/{self.id}"
                or not isinstance(root, str) or not source_archive.archives.ROOT.fullmatch(root)):
            return None
        return f"https://github.com/{repo}/tree/{self.commit}/{root}"

    @property
    def fetch_command(self) -> str | None:
        """Retrieve exact admitted files; no moving pull-request ref is involved."""
        url = self.archive_url
        if not url:
            return None
        return f"curl --fail --location {shlex.quote(url)} --output source.zip && unzip source.zip"

    @property
    def commit_url(self) -> str | None:
        if self.source_repo.startswith("https://github.com/"):
            return f"{self.source_repo.removesuffix('.git')}/commit/{self.commit}"
        return None

    @property
    def pr_repository(self) -> str | None:
        """The PR's base repository, retained in its URL even after configuration changes."""
        match = re.fullmatch(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38}/"
                             r"[A-Za-z0-9_.-]{1,100})/pull/([1-9][0-9]*)", self.pr_url or "")
        if match and int(match[2]) == self.pr_number:
            return match[1]
        return None


class GithubReport(Base):
    """Durable result outbox. A failed GitHub request must not lose a proof's verdict."""
    __tablename__ = "github_reports"
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


def schedule_report(session, sub: Submission) -> None:
    if sub.pr_number is None:
        return
    session.flush()
    report = session.get(GithubReport, sub.id)
    if report is None:
        session.add(GithubReport(submission_id=sub.id))
    else:
        report.version += 1
        report.next_attempt = utcnow()


is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if is_sqlite else {})
if is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def local_lock(name: str, *, blocking: bool = True, shared: bool = False):
    """Lock one-host service work across threads and processes; shared readers may coexist.

    Keep the lock file in place: unlinking a locked inode would let another worker bypass it.
    Locks are released automatically when a process dies.
    """
    with (settings.data_dir / f"{name}.lock").open("a") as lock:
        fcntl.flock(lock, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) |
                    (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def init_db() -> None:
    with local_lock("schema"):
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            # Older caches carry a NOT NULL `baseline` column that new rows no longer fill.
            if "baseline" in {c["name"] for c in inspect(conn).get_columns("submissions")}:
                conn.exec_driver_sql("ALTER TABLE submissions DROP COLUMN baseline")


def get_session():
    with SessionLocal() as session:
        yield session
