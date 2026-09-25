"""Synthetic explainable scoring and cleanup-report snapshots for GSA-005."""

from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from gmail_storage_auditor.cleanup_report import render_cleanup_report
from gmail_storage_auditor.duplicates import analyze_duplicates
from gmail_storage_auditor.inventory import Attachment, Hint, Inventory, Message, Scope
from gmail_storage_auditor.policy import PolicyError, ScoringPolicy, load_scoring_policy
from gmail_storage_auditor.risk import classify_risk
from gmail_storage_auditor.scoring import CleanupPlan, score_cleanup


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture():
    attachment = (Attachment("fabricated-record.pdf", 100),)
    messages = (
        Message("retained", 1_000, AS_OF, "thread", "received", attachment, True,
                (Hint("original", "synthetic fixture"),)),
        Message("review-copy", 800, AS_OF, "thread", "sent", attachment, True,
                (Hint("forwarded", "synthetic fixture"),)),
        Message("unknown-size-copy", None, AS_OF, "thread", "sent", attachment, True,
                (Hint("forwarded", "synthetic fixture"),)),
        Message("unique-protected", 50_000, AS_OF, hints=(Hint("legal", "synthetic fixture"),)),
    )
    inventory = Inventory(Scope("fabricated scoring", synthetic=True), AS_OF, messages, True, None, 1)
    duplicates = analyze_duplicates(inventory)
    return score_cleanup(duplicates, classify_risk(inventory, duplicates))


class ScoringTests(unittest.TestCase):
    def test_retention_and_risk_gate_size_and_explain_every_score(self):
        plan = fixture()
        by_ref = {item.message_ref: item for item in plan.candidates}
        self.assertEqual((by_ref["review-copy"].recommendation, by_ref["review-copy"].estimated_savings_bytes), ("review", 800))
        self.assertEqual(by_ref["unknown-size-copy"].score, None)
        self.assertEqual((by_ref["retained"].recommendation, by_ref["retained"].estimated_savings_bytes), ("keep", 0))
        self.assertEqual((by_ref["unique-protected"].recommendation, by_ref["unique-protected"].estimated_savings_bytes), ("keep", 0))
        self.assertTrue(all(item.components and item.evidence for item in plan.candidates))
        self.assertEqual(len({item.message_ref for item in plan.candidates}), 4)

    def test_numeric_policy_is_configurable_without_changing_recommendations(self):
        base = fixture()
        custom = ScoringPolicy("0.1", 50, 40, 5, 6)
        duplicates = base.duplicates
        changed = score_cleanup(duplicates, classify_risk(duplicates.inventory, duplicates), policy=custom)
        before = {x.message_ref: x for x in base.candidates}["review-copy"]
        after = {x.message_ref: x for x in changed.candidates}["review-copy"]
        self.assertNotEqual(before.score, after.score)
        self.assertEqual(before.recommendation, after.recommendation)

    def test_invalid_or_weakened_scoring_policy_fails_closed(self):
        text = """version: 0.1
scoring:
  source_supported_confidence_percent: 101
  strong_metadata_confidence_percent: 60
  high_risk_weight: 4
  unknown_risk_weight: 1
"""
        with patch("pathlib.Path.read_text", return_value=text), self.assertRaises(PolicyError):
            load_scoring_policy("synthetic-policy.yaml")

        for policy in (
            lambda: ScoringPolicy("0.1", 101, 60, 4, 5),
            lambda: ScoringPolicy("0.1", 85, 60, 0, 5),
            lambda: ScoringPolicy("0.1", 85, 60, 4, 5, require_reason=False),
            lambda: ScoringPolicy("0.1", 85, 60, 4, 5, conceptual_formula="size"),
        ):
            with self.subTest(policy=policy), self.assertRaises(PolicyError):
                policy()

    def test_duplicate_or_unsupported_scoring_keys_fail_closed(self):
        base = """version: 0.1
scoring:
  model: explainable
  conceptual_formula: "space_saved * confidence / risk"
  require_reason: true
  source_supported_confidence_percent: 85
  strong_metadata_confidence_percent: 60
  high_risk_weight: 4
  unknown_risk_weight: 5
"""
        for text in (
            base + "  unknown_risk_weight: 6\n",
            base + "  undocumented_knob: 1\n",
        ):
            with self.subTest(text=text), patch("pathlib.Path.read_text", return_value=text):
                with self.assertRaises(PolicyError):
                    load_scoring_policy("synthetic-policy.yaml")

    def test_classifications_must_cover_inventory_exactly_once(self):
        plan = fixture()
        classifications = classify_risk(plan.duplicates.inventory, plan.duplicates)
        with self.assertRaises(ValueError):
            score_cleanup(plan.duplicates, classifications[:-1])
        weakened = (replace(classifications[0], recommendation="safe"), *classifications[1:])
        with self.assertRaises(ValueError):
            score_cleanup(plan.duplicates, weakened)

    def test_same_refs_with_different_observations_are_rejected(self):
        plan = fixture()
        classifications = classify_risk(plan.duplicates.inventory, plan.duplicates)
        changed_message = replace(plan.duplicates.inventory.messages[0], size_estimate_bytes=99_999)
        changed_inventory = replace(
            plan.duplicates.inventory,
            messages=(changed_message, *plan.duplicates.inventory.messages[1:]),
        )
        changed_duplicates = analyze_duplicates(changed_inventory)
        with self.assertRaises(ValueError):
            score_cleanup(changed_duplicates, classifications)

    def test_same_inventory_with_different_duplicate_analysis_is_rejected(self):
        plan = fixture()
        classifications = classify_risk(plan.duplicates.inventory, plan.duplicates)
        changed_duplicates = replace(plan.duplicates, clusters=(), retained_refs=())
        with self.assertRaises(ValueError):
            score_cleanup(changed_duplicates, classifications)

    def test_risk_and_scoring_policy_versions_must_match(self):
        plan = fixture()
        classifications = classify_risk(plan.duplicates.inventory, plan.duplicates)
        changed_policy = ScoringPolicy("0.2", 85, 60, 4, 5)
        with self.assertRaises(ValueError):
            score_cleanup(plan.duplicates, classifications, policy=changed_policy)


class CleanupReportSnapshotTests(unittest.TestCase):
    def test_synthetic_markdown_snapshot(self):
        expected = (Path(__file__).parent / "snapshots" / "cleanup_plan.md").read_text(encoding="utf-8")
        with patch("socket.socket", side_effect=AssertionError("network")), patch("builtins.open", side_effect=AssertionError("file I/O")):
            actual = render_cleanup_report(fixture())
            self.assertEqual(actual, expected)
            self.assertEqual(render_cleanup_report(fixture()), expected)

    def test_cumulative_savings_across_populated_tiers_and_unknown_sizes(self):
        plan = fixture()
        template = plan.candidates[0]
        candidates = (
            replace(template, message_ref="safe", recommendation="safe", estimated_savings_bytes=100),
            replace(template, message_ref="review", recommendation="review", estimated_savings_bytes=200),
            replace(template, message_ref="aggressive", recommendation="aggressive", estimated_savings_bytes=None),
            replace(template, message_ref="keep", recommendation="keep", estimated_savings_bytes=0),
        )
        report = render_cleanup_report(CleanupPlan(plan.duplicates, plan.policy_version, candidates))
        for row in (
            "| Safe | 100 bytes | 100 bytes | 0 |",
            "| Review | 200 bytes | 300 bytes | 0 |",
            "| Aggressive | 0 bytes | 300 bytes | 1 |",
            "| Keep | 0 bytes | 300 bytes | 1 |",
        ):
            self.assertIn(row, report)


if __name__ == "__main__":
    unittest.main()
