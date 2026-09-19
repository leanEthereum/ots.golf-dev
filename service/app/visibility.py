"""Whether a stored submission belongs in the public view."""
from .config import settings
from .db import Submission


def visible(sub: Submission) -> bool:
    """Disabling demo mode also hides fixtures already stored in the database."""
    return settings.phony or not sub.detail_dict.get("demo")
