"""Whether a stored submission belongs in the public view."""
from .config import settings
from . import contract
from .db import Submission


def visible(sub: Submission) -> bool:
    """Disabling demo mode also hides fixtures already stored in the database."""
    return contract.track(sub.track) is not None and (settings.phony or not sub.detail_dict.get("demo"))
