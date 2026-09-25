"""Report-only storage analysis over supplied metadata. No mailbox connection."""

from .cleanup_report import render_cleanup_report
from .scoring import CleanupCandidate, CleanupPlan, score_cleanup

__all__ = ("CleanupCandidate", "CleanupPlan", "render_cleanup_report", "score_cleanup")
