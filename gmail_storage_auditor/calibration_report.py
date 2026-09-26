"""Deterministic Markdown rendering for advisory calibration reports."""

from .calibration import CalibrationReport
from .report import _cell


def render_calibration_report(report: CalibrationReport) -> str:
    if not isinstance(report, CalibrationReport):
        raise ValueError("calibration_report_required")
    lines = [
        "# Calibration retrospective", "",
        f"Policy version: {_cell(report.policy_version)}",
        f"Trigger: {_cell(report.trigger)}",
        "Advisory only: this report cannot change policy or authorize mailbox actions.", "",
        "## Observed signals", "",
        "| Signal | Value | Denominator | Observation |",
        "| --- | ---: | ---: | --- |",
    ]
    for signal in report.signals:
        value = "unknown" if signal.value is None else str(signal.value)
        denominator = "n/a" if signal.denominator is None else str(signal.denominator)
        lines.append(
            f"| {_cell(signal.name)} | {value} | {denominator} | {_cell(signal.observation)} |"
        )
    lines.extend(["", "## Policy judgments", ""])
    for judgment in report.judgments:
        lines.append(
            f"- [{_cell(judgment.severity)}] {_cell(judgment.code)}: {_cell(judgment.rationale)}"
        )
    lines.extend(["", "## Policy-change proposals", ""])
    if not report.proposals:
        lines.append("No proposal supplied.")
    for proposal in report.proposals:
        lines.extend([
            f"### {_cell(proposal.title)}", "",
            f"Rationale: {_cell(proposal.rationale)}",
            f"Safety impact: {_cell(proposal.safety_impact)}",
            "Status: requires human review; not applied.",
            "Required regression tests:",
            *(f"- {_cell(item)}" for item in proposal.regression_tests),
            "",
        ])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {_cell(item)}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"
