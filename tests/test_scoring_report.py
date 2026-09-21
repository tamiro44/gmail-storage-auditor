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
from gmail_storage_auditor.scoring import score_cleanup


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
        custom = ScoringPolicy("test", 50, 40, 5, 6)
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

    def test_classifications_must_cover_inventory_exactly_once(self):
        plan = fixture()
        classifications = classify_risk(plan.duplicates.inventory, plan.duplicates)
        with self.assertRaises(ValueError):
            score_cleanup(plan.duplicates, classifications[:-1])
        weakened = (replace(classifications[0], recommendation="safe"), *classifications[1:])
        with self.assertRaises(ValueError):
            score_cleanup(plan.duplicates, weakened)


class CleanupReportSnapshotTests(unittest.TestCase):
    def test_synthetic_markdown_snapshot(self):
        expected = (Path(__file__).parent / "snapshots" / "cleanup_plan.md").read_text(encoding="utf-8")
        with patch("socket.socket", side_effect=AssertionError("network")), patch("builtins.open", side_effect=AssertionError("file I/O")):
            actual = render_cleanup_report(fixture())
            self.assertEqual(actual, expected)
            self.assertEqual(render_cleanup_report(fixture()), expected)


if __name__ == "__main__":
    unittest.main()
