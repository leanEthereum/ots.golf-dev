"""Settings from the environment. Everything has a localhost default."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SERVICE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPO_ROOT = SERVICE_DIR.parent
DEFAULT_CONTRACT_REPO = "leanEthereum/ots.golf-dev"
DEFAULT_SUBMISSIONS_REPO = "leanEthereum/ots.golf-submissions"


@dataclass
class Settings:
    environment: str = os.environ.get("OTS_ENV", "development")
    role: str = os.environ.get("OTS_ROLE", "web")
    repo_root: Path = Path(os.environ.get("OTS_REPO_ROOT", str(DEFAULT_REPO_ROOT))).resolve()
    data_dir: Path = Path(os.environ.get("OTS_DATA_DIR", str(SERVICE_DIR / "data"))).resolve()
    work_dir: Path | None = Path(os.environ["OTS_WORK_DIR"]).resolve() if os.environ.get("OTS_WORK_DIR") else None
    base_url: str = os.environ.get("OTS_BASE_URL", "http://localhost:8000").rstrip("/")
    github_webhook_secret: str = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    github_token: str = os.environ.get("GITHUB_TOKEN", "")
    contract_repo: str = os.environ.get("OTS_CONTRACT_REPO", DEFAULT_CONTRACT_REPO)
    submissions_repo: str = os.environ.get("OTS_SUBMISSIONS_REPO", "")  # empty keeps webhook admission closed
    # The account whose pull-request comments carry verdicts; by default the token's own login.
    bot_login: str = os.environ.get("OTS_BOT_LOGIN", "")
    # Invented demo submissions are opt-in for a local preview. Production shows real rows.
    phony: bool = os.environ.get("OTS_PHONY", "0") == "1"
    # Rebuild missing submissions from GitHub when the website starts.
    resync_on_start: bool = os.environ.get("OTS_RESYNC_ON_START", "1") == "1"
    queue_cap: int = int(os.environ.get("OTS_QUEUE_CAP", "20"))
    max_inflight_per_user: int = int(os.environ.get("OTS_MAX_INFLIGHT_PER_USER", "2"))
    database_url: str = ""

    def __post_init__(self) -> None:
        if self.environment not in {"development", "production"}:
            raise ValueError("OTS_ENV must be development or production")
        if self.role not in {"web", "worker"}:
            raise ValueError("OTS_ROLE must be web or worker")
        if self.queue_cap < 1 or self.max_inflight_per_user < 1:
            raise ValueError("queue limits must be positive")
        url = urlsplit(self.base_url)
        if (url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password
                or url.query or url.fragment or url.path):
            raise ValueError("OTS_BASE_URL must be an http(s) origin without credentials, a path or a query")
        for key, repo in (("OTS_CONTRACT_REPO", self.contract_repo), ("OTS_SUBMISSIONS_REPO", self.submissions_repo)):
            if repo and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo):
                raise ValueError(f"{key} must be owner/repository")
        if self.submissions_repo and self.submissions_repo.lower() == self.contract_repo.lower():
            raise ValueError("contract and submissions must use separate repositories")
        if self.environment == "production":
            if url.scheme != "https" or not self.contract_repo or not self.submissions_repo:
                raise ValueError("production requires an HTTPS origin and both repository settings")
            if self.role == "web" and (not self.github_token or len(self.github_webhook_secret) < 32):
                raise ValueError("the production web service requires a GitHub token and a webhook secret of at least 32 characters")
            if self.role == "worker" and (self.github_token or self.github_webhook_secret):
                raise ValueError("the production verifier worker must not receive GitHub secrets")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(exist_ok=True)
        self.work_dir = (self.work_dir or self.data_dir / "work").resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = os.environ.get("OTS_DATABASE_URL", f"sqlite:///{self.data_dir / 'ots.db'}")

    @property
    def contract_url(self) -> str:
        return "https://github.com/" + (self.contract_repo or DEFAULT_CONTRACT_REPO)

    @property
    def submissions_url(self) -> str:
        return "https://github.com/" + (self.submissions_repo or DEFAULT_SUBMISSIONS_REPO)


settings = Settings()
