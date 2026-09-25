"""Synthetic regression tests for the advisory calibration loop."""

from dataclasses import replace
from unittest.mock import patch
import unittest

from gmail_storage_auditor.calibration import (
    CalibrationConfig,
    CalibrationError,
    DecisionAggregate,
    PolicyChangeProposal,
    SyntheticEvaluation,
    evaluate_calibration,
)
from gmail_storage_auditor.calibration_report import render_calibration_report


def evaluation(index, **changes):
    item = SyntheticEvaluation(
        fixture_id=f"fixture-{index:02d}",
        pattern="source-supported duplicate",
        expected_recommendation="review",
        actual_recommendation="review",
        expected_protected=False,
        retained_copy_required=True,
        retained_copy_preserved=True,
        estimated_bytes=1_000 + index,
        expected_confidence_percent=85,
        actual_confidence_percent=85,
        score=100,
    )
    return replace(item, **changes)


class CalibrationTests(unittest.TestCase):
    def test_clean_synthetic_cohort_reports_facts_without_inventing_findings(self):
        report = evaluate_calibration(
            "0.1", "manual_milestone", tuple(evaluation(i) for i in range(10))
        )
        signals = {item.name: item.value for item in report.signals}
        self.assertEqual(signals["evaluations"], 10)
        self.assertEqual(signals["recommendation_mismatches"], 0)
        self.assertEqual(signals["retained_copy_violations"], 0)
        self.assertEqual(report.judgments[0].code, "no_investigation_trigger")
        self.assertEqual(report.proposals, ())

    def test_safety_drift_confidence_size_and_rejections_are_measured(self):
        evaluations = [evaluation(i, score=1) for i in range(10)]
        evaluations[0] = evaluation(
            0, actual_recommendation="safe", expected_protected=True,
            retained_copy_preserved=False, actual_confidence_percent=40,
            estimated_bytes=1_000_000, score=100,
        )
        evaluations[1] = evaluation(1, actual_recommendation="keep", score=1)
        aggregate = DecisionAggregate(
            "source-supported duplicate", "review", approvals=2, rejections=8
        )
        report = evaluate_calibration(
            "0.1", "fixture_suite_change", tuple(evaluations), aggregates=(aggregate,)
        )
        signals = {item.name: item.value for item in report.signals}
        self.assertEqual(signals["false_safe"], 1)
        self.assertEqual(signals["missed_protected"], 1)
        self.assertEqual(signals["unexpected_keep"], 1)
        self.assertEqual(signals["retained_copy_violations"], 1)
        self.assertEqual(signals["confidence_mismatches"], 1)
        self.assertEqual(signals["recurring_rejection_patterns"], 1)
        codes = {item.code for item in report.judgments}
        self.assertTrue({
            "safety_regression", "possible_size_dominance", "confidence_drift",
            "recurring_rejection_pattern", "possible_overprotection",
        }.issubset(codes))

    def test_small_cohort_is_limited_except_for_policy_version_review(self):
        small = (evaluation(1),)
        milestone = evaluate_calibration("0.1", "manual_milestone", small)
        version_change = evaluate_calibration("0.2", "policy_version_change", small)
        self.assertIn("insufficient_sample", {item.code for item in milestone.judgments})
        self.assertNotIn("insufficient_sample", {item.code for item in version_change.judgments})

    def test_proposals_require_rationale_tests_and_cannot_weaken_safety(self):
        proposal = PolicyChangeProposal(
            "Raise duplicate threshold",
            "Synthetic false positives recur in the fixed cohort.",
            ("Add conflicting-content fixture", "Assert recommendation remains Review"),
            "strengthen",
        )
        report = evaluate_calibration(
            "0.1", "policy_version_change", (evaluation(1),), proposals=(proposal,)
        )
        self.assertEqual(report.proposals, (proposal,))
        for kwargs in (
            {"rationale": ""}, {"regression_tests": ()}, {"safety_impact": "weaken"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(CalibrationError):
                replace(proposal, **kwargs)

    def test_real_feedback_and_invalid_private_shapes_fail_closed(self):
        with self.assertRaisesRegex(CalibrationError, "real_feedback_disabled"):
            DecisionAggregate("pattern", "review", 10, 2, source="real")
        with self.assertRaises(CalibrationError):
            evaluate_calibration("0.1", "continuous", (evaluation(1),))
        with self.assertRaises(CalibrationError):
            evaluate_calibration("0.1", "manual_milestone", ())
        with self.assertRaises(CalibrationError):
            CalibrationConfig(size_dominance_percent=101)

    def test_report_is_deterministic_advisory_and_has_separate_sections(self):
        proposal = PolicyChangeProposal(
            "Investigate weights", "Size contribution crossed the fixture threshold.",
            ("Add balanced-size cohort",), "preserve",
        )
        report = evaluate_calibration(
            "0.1", "policy_version_change", (evaluation(1),), proposals=(proposal,)
        )
        with patch("builtins.open", side_effect=AssertionError("file I/O")), patch(
            "socket.socket", side_effect=AssertionError("network")
        ):
            rendered = render_calibration_report(report)
            self.assertEqual(render_calibration_report(report), rendered)
        for text in (
            "## Observed signals", "## Policy judgments", "## Policy-change proposals",
            "requires human review; not applied", "cannot change policy",
            "Real-mailbox content", "## Limitations",
        ):
            self.assertIn(text, rendered)


if __name__ == "__main__":
    unittest.main()
