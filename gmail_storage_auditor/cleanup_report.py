"""Deterministic Markdown presentation of an explainable cleanup plan."""

from .report import _cell
from .scoring import CleanupPlan


TIERS = ("safe", "review", "aggressive", "keep")


def _bytes(value: int | None) -> str:
    return "unknown" if value is None else f"{value:,} bytes"


def render_cleanup_report(plan: CleanupPlan) -> str:
    inventory = plan.duplicates.inventory
    lines = [
        "# Cleanup plan" + (" (synthetic fixture)" if inventory.scope.synthetic else ""), "",
        f"Policy version: {_cell(plan.policy_version)}",
        "Analysis only: recommendations do not authorize mailbox changes or deletion.",
        "Savings are whole-message provider estimates, not measured reclaimed storage. Scores are derived ranking values.",
        ("Synthetic fixture values are illustrative; they are not mailbox measurements." if inventory.scope.synthetic else
         "No illustrative values are inserted into this report."),
        "Unknown values remain unknown. Retained and Keep items contribute zero estimated savings.", "",
        "## Pareto summary", "",
        "| Through tier | Incremental estimated savings | Cumulative estimated savings | Unknown-size candidates |",
        "| --- | ---: | ---: | ---: |",
    ]
    cumulative = 0
    unknown_cumulative = 0
    for tier in TIERS:
        members = tuple(c for c in plan.candidates if c.recommendation == tier)
        known = sum(c.estimated_savings_bytes for c in members if c.estimated_savings_bytes is not None)
        unknown = sum(c.estimated_savings_bytes is None for c in members)
        cumulative += known
        unknown_cumulative += unknown
        lines.append(f"| {_cell(tier.title())} | {known:,} bytes | {cumulative:,} bytes | {unknown_cumulative} |")
    lines.extend(["", "Safe recovery is shown first; Review and Aggressive add progressively less conservative options. Keep adds no recovery.", ""])
    for tier in TIERS:
        lines.extend([f"## {tier.title()}", ""])
        members = tuple(c for c in plan.candidates if c.recommendation == tier)
        if not members:
            lines.extend(["No candidates.", ""])
            continue
        for candidate in members:
            confidence = "unknown" if candidate.confidence_percent is None else f"{candidate.confidence_percent}% heuristic"
            score = "unknown" if candidate.score is None else f"{candidate.score:,}"
            retained = ", ".join(_cell(ref) for ref in candidate.retained_copy_refs) or "none"
            lines.extend([
                f"### {_cell(candidate.message_ref)}", "",
                f"- Estimated savings: {_bytes(candidate.estimated_savings_bytes)}",
                f"- Confidence: {confidence} ({_cell(candidate.confidence_basis)})",
                f"- Risk tier: {_cell(candidate.risk_tier)}",
                f"- Recommendation: {_cell(candidate.recommendation)}",
                f"- Cleanup score: {score}",
                f"- Retained-copy information: {retained}",
                "- Evidence: " + "; ".join(_cell(item) for item in candidate.evidence),
                "- Score components: " + "; ".join(
                    f"{item.name}={_cell(item.value)} ({_cell(item.explanation)})" for item in candidate.components
                ), "",
            ])
    return "\n".join(lines).rstrip() + "\n"
