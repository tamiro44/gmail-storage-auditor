"""Advisory calibration over synthetic evaluations; no policy or action capability."""

from dataclasses import dataclass


RECOMMENDATIONS = ("safe", "review", "aggressive", "keep")
TRIGGERS = ("manual_milestone", "policy_version_change", "fixture_suite_change")


class CalibrationError(ValueError):
    """Invalid privacy-safe calibration input."""


def _text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CalibrationError(f"{field}_required")


@dataclass(frozen=True)
class CalibrationConfig:
    minimum_evaluations: int = 10
    minimum_feedback_cohort: int = 5
    mismatch_rate_percent: int = 20
    rejection_rate_percent: int = 60
    size_dominance_percent: int = 70
    confidence_tolerance_points: int = 10

    def __post_init__(self) -> None:
        values = (
            self.minimum_evaluations, self.minimum_feedback_cohort,
            self.mismatch_rate_percent, self.rejection_rate_percent,
            self.size_dominance_percent, self.confidence_tolerance_points,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise CalibrationError("calibration_config_invalid")
        if self.minimum_evaluations < 1 or self.minimum_feedback_cohort < 1:
            raise CalibrationError("calibration_minimum_invalid")
        if any(value > 100 for value in values[2:]):
            raise CalibrationError("calibration_threshold_invalid")


@dataclass(frozen=True)
class SyntheticEvaluation:
    """One fabricated expected/actual decision with no mailbox identifiers."""

    fixture_id: str
    pattern: str
    expected_recommendation: str
    actual_recommendation: str
    expected_protected: bool
    retained_copy_required: bool
    retained_copy_preserved: bool
    estimated_bytes: int | None
    expected_confidence_percent: int | None
    actual_confidence_percent: int | None
    score: int | None

    def __post_init__(self) -> None:
        _text(self.fixture_id, "fixture_id")
        _text(self.pattern, "pattern")
        if self.expected_recommendation not in RECOMMENDATIONS:
            raise CalibrationError("expected_recommendation_invalid")
        if self.actual_recommendation not in RECOMMENDATIONS:
            raise CalibrationError("actual_recommendation_invalid")
        for value in (
            self.expected_protected, self.retained_copy_required,
            self.retained_copy_preserved,
        ):
            if type(value) is not bool:
                raise CalibrationError("evaluation_flag_invalid")
        if not self.retained_copy_required and not self.retained_copy_preserved:
            raise CalibrationError("retained_copy_observation_invalid")
        for value in (self.estimated_bytes, self.score):
            if value is not None and (type(value) is not int or value < 0):
                raise CalibrationError("evaluation_number_invalid")
        for value in (self.expected_confidence_percent, self.actual_confidence_percent):
            if value is not None and (type(value) is not int or not 0 <= value <= 100):
                raise CalibrationError("confidence_invalid")


@dataclass(frozen=True)
class DecisionAggregate:
    """Non-identifying synthetic outcome counts for one broad pattern."""

    pattern: str
    recommendation: str
    approvals: int
    rejections: int
    source: str = "synthetic"

    def __post_init__(self) -> None:
        _text(self.pattern, "aggregate_pattern")
        if self.recommendation not in RECOMMENDATIONS:
            raise CalibrationError("aggregate_recommendation_invalid")
        if self.source != "synthetic":
            raise CalibrationError("real_feedback_disabled")
        if any(type(value) is not int or value < 0 for value in (self.approvals, self.rejections)):
            raise CalibrationError("aggregate_count_invalid")
        if self.approvals + self.rejections == 0:
            raise CalibrationError("aggregate_empty")


@dataclass(frozen=True)
class PolicyChangeProposal:
    title: str
    rationale: str
    regression_tests: tuple[str, ...]
    safety_impact: str

    def __post_init__(self) -> None:
        _text(self.title, "proposal_title")
        _text(self.rationale, "proposal_rationale")
        if (not isinstance(self.regression_tests, tuple) or not self.regression_tests
                or any(not isinstance(item, str) or not item.strip()
                       for item in self.regression_tests)):
            raise CalibrationError("proposal_regression_tests_required")
        if self.safety_impact not in ("preserve", "strengthen"):
            raise CalibrationError("proposal_cannot_weaken_safety")


@dataclass(frozen=True)
class CalibrationSignal:
    name: str
    value: int | None
    denominator: int | None
    observation: str


@dataclass(frozen=True)
class CalibrationJudgment:
    code: str
    severity: str
    rationale: str


@dataclass(frozen=True)
class CalibrationReport:
    policy_version: str
    trigger: str
    signals: tuple[CalibrationSignal, ...]
    judgments: tuple[CalibrationJudgment, ...]
    proposals: tuple[PolicyChangeProposal, ...]
    limitations: tuple[str, ...]


def _percent(numerator: int, denominator: int) -> int:
    return 0 if denominator == 0 else numerator * 100 // denominator


def evaluate_calibration(
    policy_version: str,
    trigger: str,
    evaluations: tuple[SyntheticEvaluation, ...],
    *,
    aggregates: tuple[DecisionAggregate, ...] = (),
    proposals: tuple[PolicyChangeProposal, ...] = (),
    config: CalibrationConfig | None = None,
) -> CalibrationReport:
    """Measure observations, then derive advisory judgments without changing policy."""
    _text(policy_version, "policy_version")
    if trigger not in TRIGGERS:
        raise CalibrationError("calibration_trigger_invalid")
    if (not isinstance(evaluations, tuple) or not evaluations
            or any(not isinstance(item, SyntheticEvaluation) for item in evaluations)):
        raise CalibrationError("synthetic_evaluations_required")
    if (not isinstance(aggregates, tuple)
            or any(not isinstance(item, DecisionAggregate) for item in aggregates)):
        raise CalibrationError("aggregates_invalid")
    if (not isinstance(proposals, tuple)
            or any(not isinstance(item, PolicyChangeProposal) for item in proposals)):
        raise CalibrationError("proposals_invalid")
    config = config or CalibrationConfig()
    if not isinstance(config, CalibrationConfig):
        raise CalibrationError("calibration_config_invalid")

    total = len(evaluations)
    mismatches = sum(
        item.expected_recommendation != item.actual_recommendation for item in evaluations
    )
    false_safe = sum(
        item.actual_recommendation == "safe" and item.expected_recommendation != "safe"
        for item in evaluations
    )
    missed_protected = sum(
        item.expected_protected and item.actual_recommendation in ("safe", "aggressive")
        for item in evaluations
    )
    unexpected_keep = sum(
        not item.expected_protected
        and item.expected_recommendation != "keep"
        and item.actual_recommendation == "keep"
        for item in evaluations
    )
    retained_violations = sum(
        item.retained_copy_required and not item.retained_copy_preserved
        for item in evaluations
    )
    confidence_comparable = tuple(
        item for item in evaluations
        if item.expected_confidence_percent is not None
        and item.actual_confidence_percent is not None
    )
    confidence_mismatches = sum(
        abs(item.expected_confidence_percent - item.actual_confidence_percent)
        > config.confidence_tolerance_points
        for item in confidence_comparable
    )
    scored = tuple(item for item in evaluations if item.score is not None)
    total_score = sum(item.score for item in scored)
    largest_score_share = None
    if total_score:
        largest = max(scored, key=lambda item: ((item.estimated_bytes or 0), item.fixture_id))
        largest_score_share = _percent(largest.score, total_score)

    recurring_rejections = 0
    for item in aggregates:
        cohort = item.approvals + item.rejections
        if (cohort >= config.minimum_feedback_cohort
                and _percent(item.rejections, cohort) >= config.rejection_rate_percent):
            recurring_rejections += 1

    signals = (
        CalibrationSignal("evaluations", total, None, "Synthetic fixtures evaluated."),
        CalibrationSignal("recommendation_mismatches", mismatches, total, "Expected and actual tiers differ."),
        CalibrationSignal("false_safe", false_safe, total, "Unexpected Safe recommendations."),
        CalibrationSignal("missed_protected", missed_protected, total, "Protected fixtures placed in Safe or Aggressive."),
        CalibrationSignal("unexpected_keep", unexpected_keep, total, "Unprotected fixtures retained contrary to expectations."),
        CalibrationSignal("retained_copy_violations", retained_violations, total, "Required retained copy was not preserved."),
        CalibrationSignal("confidence_mismatches", confidence_mismatches, len(confidence_comparable), "Confidence differs beyond configured tolerance."),
        CalibrationSignal("largest_message_score_share_percent", largest_score_share, 100 if largest_score_share is not None else None, "Share of total score assigned to the largest scored fixture."),
        CalibrationSignal("recurring_rejection_patterns", recurring_rejections, len(aggregates), "Adequately sized synthetic cohorts above rejection threshold."),
    )

    judgments = []
    ordinary_judgments_enabled = (
        total >= config.minimum_evaluations or trigger == "policy_version_change"
    )
    if not ordinary_judgments_enabled:
        judgments.append(CalibrationJudgment(
            "insufficient_sample", "notice",
            "The fixture cohort is below the configured milestone; avoid policy conclusions.",
        ))
    if false_safe or missed_protected or retained_violations:
        judgments.append(CalibrationJudgment(
            "safety_regression", "critical",
            "Safety signals are nonzero; investigate fixtures and preserve existing gates.",
        ))
    if (ordinary_judgments_enabled
            and _percent(mismatches, total) >= config.mismatch_rate_percent):
        judgments.append(CalibrationJudgment(
            "recommendation_drift", "review",
            "Recommendation mismatch rate reached the configured investigation threshold.",
        ))
    if ordinary_judgments_enabled and unexpected_keep:
        judgments.append(CalibrationJudgment(
            "possible_overprotection", "review",
            "Unprotected fixtures were kept contrary to expectations; inspect category breadth.",
        ))
    if (ordinary_judgments_enabled and largest_score_share is not None
            and largest_score_share >= config.size_dominance_percent):
        judgments.append(CalibrationJudgment(
            "possible_size_dominance", "review",
            "The largest fixture contributes a high share of score; inspect component balance.",
        ))
    if ordinary_judgments_enabled and confidence_mismatches:
        judgments.append(CalibrationJudgment(
            "confidence_drift", "review",
            "One or more confidence values exceeded the configured tolerance.",
        ))
    if ordinary_judgments_enabled and recurring_rejections:
        judgments.append(CalibrationJudgment(
            "recurring_rejection_pattern", "review",
            "A sufficiently large synthetic outcome cohort has repeated rejections.",
        ))
    if not judgments:
        judgments.append(CalibrationJudgment(
            "no_investigation_trigger", "notice",
            "No configured investigation threshold was reached.",
        ))

    limitations = (
        "Inputs are synthetic and do not establish real-world safety or user preference.",
        "Approval and rejection counts are preference evidence, not proof of correctness.",
        "Findings and proposals are advisory; policy changes require human review and regression tests.",
        "Real-mailbox content and real per-audit feedback are not accepted in v0.1.",
    )
    return CalibrationReport(
        policy_version, trigger, signals, tuple(judgments), proposals, limitations
    )
