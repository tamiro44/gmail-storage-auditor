"""Synthetic conservative risk-policy tests for GSA-004."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from gmail_storage_auditor.duplicates import analyze_duplicates
from gmail_storage_auditor.inventory import Attachment, Hint, Inventory, Message, Scope
from gmail_storage_auditor.policy import PolicyError, load_risk_policy
from gmail_storage_auditor.risk import RiskFinding, classify_risk


def inventory(*messages):
    return Inventory(Scope("fabricated", synthetic=True), datetime(2026, 1, 1, tzinfo=timezone.utc), tuple(messages), True, None, 1)


class RiskTests(unittest.TestCase):
    def test_checked_in_policy_drives_all_protected_categories(self):
        policy = load_risk_policy()
        self.assertEqual(policy.version, "0.1")
        for category in policy.protected_categories:
            with self.subTest(category=category):
                result, = classify_risk(inventory(Message("synthetic", hints=(Hint(category, "fabricated fixture"),))), policy=policy)
                self.assertEqual((result.risk, result.recommendation), ("high", "keep"))
                self.assertIn(category, result.categories)
                self.assertTrue(result.evidence)
                self.assertIn("Protected category", result.reasons[0])

    def test_sentimental_media_defaults_to_review_with_reason(self):
        result, = classify_risk(inventory(Message("photo", hints=(Hint("sentimental_media", "synthetic tag"),))))
        self.assertEqual(result.recommendation, "review")
        self.assertIn("Sentimental media", result.reasons[0])

    def test_protected_duplicate_is_recognized_but_never_safe(self):
        attachment = (Attachment("fabricated.pdf", 42),)
        original = Message("original", thread_ref="thread", attachments=attachment, hints=(Hint("original", "fixture"), Hint("legal", "fixture")))
        copy = Message("copy", thread_ref="thread", attachments=attachment, hints=(Hint("forwarded", "fixture"), Hint("legal", "fixture")))
        observed = inventory(original, copy)
        results = {x.message_ref: x for x in classify_risk(observed, analyze_duplicates(observed))}
        self.assertEqual(results["original"].recommendation, "keep")
        self.assertEqual(results["copy"].recommendation, "review")
        self.assertTrue(results["copy"].duplicate_clusters)
        self.assertTrue(any("does not prove" in reason for reason in results["copy"].reasons))

    def test_semantics_are_optional_advisory_and_failure_is_conservative(self):
        class Semantic:
            def classify(self, message):
                return (RiskFinding("medical", "Fabricated semantic match.", "optional semantic"),)
        result, = classify_risk(inventory(Message("x")), semantic_classifier=Semantic())
        self.assertEqual((result.recommendation, result.categories), ("keep", ("medical",)))

        class Broken:
            def classify(self, message):
                raise RuntimeError("synthetic failure")
        failed, = classify_risk(inventory(Message("x")), semantic_classifier=Broken())
        self.assertEqual((failed.recommendation, failed.risk), ("review", "unknown"))
        self.assertNotIn("synthetic failure", repr(failed))

        class Malformed:
            def classify(self, message):
                return (RiskFinding("", "fabricated evidence", "fixture"),)
        malformed, = classify_risk(inventory(Message("x")), semantic_classifier=Malformed())
        self.assertEqual((malformed.recommendation, malformed.risk), ("review", "unknown"))
        self.assertIn("classification_uncertain", malformed.categories)

    def test_missing_or_weakened_policy_fails_closed(self):
        weakened = """version: 0.1
protected_categories:
  tax: protected
  legal: review
  financial: protected
  medical: protected
  identity: protected
  employment: protected
  signed_documents: protected
sentimental_media:
  default: review
"""
        with patch("pathlib.Path.read_text", return_value=weakened):
            with self.assertRaises(PolicyError):
                load_risk_policy("synthetic-policy.yaml")


if __name__ == "__main__":
    unittest.main()
