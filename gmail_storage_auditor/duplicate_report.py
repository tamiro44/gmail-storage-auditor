"""Private, analysis-only duplicate report over the existing inventory."""

from .duplicates import DuplicateAnalysis
from .report import _cell, render_inventory


def render_duplicates(analysis: DuplicateAnalysis) -> str:
    lines = [render_inventory(analysis.inventory).rstrip(), "", "## Duplicate metadata analysis", "",
             "Analysis only: no removal recommendations, risk tiers, scores, or savings estimates.",
             "Confidence is qualitative metadata evidence, not a calibrated probability of identical content.",
             "Retained copies are proposals; authority and whole-message redundancy require review.",
             "All proposed retained references across overlapping clusters: "
             + (", ".join(_cell(ref) for ref in analysis.retained_refs) or "none"), ""]
    if not analysis.clusters:
        lines.append("No exact attachment metadata matches across observed messages; this does not prove uniqueness.")
    for cluster in analysis.clusters:
        lines.extend([
            f"### {_cell(cluster.filename)} ({cluster.size_bytes} exact bytes)", "",
            "Members: " + ", ".join(_cell(ref) for ref in cluster.members),
            f"Confidence: {cluster.confidence}",
            f"Proposed retained copy: {_cell(cluster.retained_ref)}; authority: {cluster.authority}",
            f"Retention reason: {cluster.retention_reason}",
            "Evidence: " + "; ".join(_cell(item) for item in cluster.evidence),
            "Limitations: " + " ".join(_cell(item) for item in cluster.limitations), "",
        ])
    return "\n".join(lines) + "\n"
