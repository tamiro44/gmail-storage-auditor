"""Synthetic GSA-003 regressions, including the existing Gmail read boundary."""

from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import unittest
from unittest.mock import patch

from gmail_storage_auditor import duplicate_demo, gmail_cli
from gmail_storage_auditor.demo import AS_OF
from gmail_storage_auditor.duplicates import analyze_duplicates
from gmail_storage_auditor.duplicate_report import render_duplicates
from gmail_storage_auditor.gmail import GmailReader, GMAIL_SCOPES
from gmail_storage_auditor.inventory import Attachment, Hint, Message, Page, Scope, collect_inventory


class ReadOnlySource:
    def __init__(self, messages):
        self.messages = messages

    def read_page(self, scope, cursor):
        return Page(tuple(self.messages), complete=True)

    def __getattr__(self, name):
        raise AssertionError("Unexpected source capability requested")


def inventory(*messages):
    return collect_inventory(ReadOnlySource(messages), Scope("synthetic", synthetic=True),
                             as_of=AS_OF, max_pages=1)


def message(ref, **kwargs):
    kwargs.setdefault("attachments", (Attachment("sample.bin", 12),))
    return Message(ref, **kwargs)


class DuplicateTests(unittest.TestCase):
    def test_exact_match_has_evidence_and_retained_member_without_authority_claim(self):
        result = analyze_duplicates(inventory(message("b"), message("a")))
        cluster, = result.clusters
        self.assertEqual(cluster.members, ("a", "b"))
        self.assertEqual(cluster.confidence, "strong_metadata_match")
        self.assertIn("exact_filename_and_byte_size", cluster.evidence)
        self.assertEqual(cluster.retained_ref, "a")
        self.assertEqual(cluster.authority, "unresolved")
        self.assertEqual(result.retained_refs, ("a",))

    def test_only_exact_known_keys_match_including_zero(self):
        for attachment in (Attachment("sample.bin", None), Attachment(None, 12),
                           Attachment("Sample.bin", 12), Attachment("sample.bin", 13),
                           Attachment("sample.bin ", 12)):
            with self.subTest(attachment=attachment):
                self.assertFalse(analyze_duplicates(inventory(message("a"), message("b", attachments=(attachment,)))).clusters)
        zero = (Attachment("empty.bin", 0),)
        self.assertEqual(len(analyze_duplicates(inventory(message("a", attachments=zero), message("b", attachments=zero))).clusters), 1)

    def test_repeated_attachment_or_observation_does_not_create_cluster(self):
        item = message("a", attachments=(Attachment("sample.bin", 12),) * 2)
        self.assertFalse(analyze_duplicates(inventory(item, item)).clusters)
        self.assertFalse(analyze_duplicates(inventory()).clusters)

    def test_original_forward_and_direction_patterns_are_explicit(self):
        original = message("z", thread_ref="t", hints=(Hint("original", "fixture source"),))
        forward = message("a", thread_ref="t", direction="sent", hints=(Hint("forwarded", "fixture source"),))
        cluster, = analyze_duplicates(inventory(original, forward, message("b", direction="self_sent"))).clusters
        self.assertEqual(cluster.retained_ref, "z")
        self.assertEqual(cluster.authority, "source_supported")
        self.assertIn("same_thread_original_forward: z, a", cluster.evidence)
        self.assertTrue(any("self_sent_copy_pattern" in evidence for evidence in cluster.evidence))
        self.assertTrue(any("sent_copy_pattern" in evidence for evidence in cluster.evidence))
        self.assertTrue(any("fixture source" in evidence for evidence in cluster.evidence))

    def test_missing_different_thread_or_missing_original_cannot_establish_authority(self):
        for thread in (None, "other"):
            cluster, = analyze_duplicates(inventory(
                message("z", thread_ref=thread, hints=(Hint("original", "fixture"),)),
                message("a", thread_ref="t", hints=(Hint("forwarded", "fixture"),)),
            )).clusters
            self.assertEqual(cluster.authority, "unresolved")
        cluster, = analyze_duplicates(inventory(message("z", direction="received"), message("a", direction="sent"))).clusters
        self.assertEqual(cluster.authority, "unresolved")

    def test_conflicting_or_multiple_originals_remain_unresolved(self):
        original = message("z", thread_ref="t", hints=(Hint("original", "fixture"),))
        forward = message("a", thread_ref="t", hints=(Hint("forwarded", "fixture"),))
        for extra in (replace(original, ref="b"), replace(original, ref="b", thread_ref="other"), message("b", hints=(Hint("original", "x"), Hint("forwarded", "y")))):
            cluster, = analyze_duplicates(inventory(original, forward, extra)).clusters
            self.assertEqual(cluster.authority, "unresolved")

    def test_relationships_alone_do_not_merge_different_attachments(self):
        self.assertFalse(analyze_duplicates(inventory(
            message("a", thread_ref="t", hints=(Hint("original", "fixture"),)),
            message("b", thread_ref="t", direction="self_sent", attachments=(), hints=(Hint("forwarded", "fixture"),)),
        )).clusters)

    def test_overlap_does_not_transitively_merge_and_all_retained_refs_are_preserved(self):
        x, y = Attachment("x", 1), Attachment("y", 2)
        messages = (message("a", attachments=(x,)), message("b", attachments=(x, y)), message("c", attachments=(y,)))
        result = analyze_duplicates(inventory(*messages))
        self.assertEqual(tuple(c.members for c in result.clusters), (("a", "b"), ("b", "c")))
        self.assertEqual(result.retained_refs, ("a", "b"))
        self.assertEqual(result, analyze_duplicates(inventory(*reversed(messages))))
        for cluster in result.clusters:
            self.assertIn(cluster.retained_ref, cluster.members)

    def test_partial_missing_context_and_unknown_size_remain_visible(self):
        result = analyze_duplicates(replace(inventory(message("a"), message("b")), complete=False, partial_reason="page_limit"))
        report = render_duplicates(result)
        for text in ("Scan: partial", "targeted scope only", "Partial inventory", "incomplete or unknown", "whole-message", "unknown", "no removal recommendations"):
            self.assertIn(text, report)
        self.assertFalse(hasattr(result, "removal_refs"))

    def test_report_escapes_untrusted_metadata_and_preserves_no_match_uncertainty(self):
        attachment = (Attachment("<script>|\nfile", 1),)
        report = render_duplicates(analyze_duplicates(inventory(message("a", attachments=attachment), message("b", attachments=attachment))))
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;&#124; file", report)
        self.assertIn("does not prove uniqueness", render_duplicates(analyze_duplicates(inventory())))

    def test_demo_is_deterministic_with_network_blocked(self):
        outputs = []
        with patch("socket.socket", side_effect=AssertionError("network")), patch("socket.create_connection", side_effect=AssertionError("network")), patch("socket.getaddrinfo", side_effect=AssertionError("network")):
            for _ in range(2):
                output = StringIO()
                with redirect_stdout(output):
                    duplicate_demo.main()
                outputs.append(output.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("authority: source_supported", outputs[0])

    def test_opt_in_gmail_cli_reuses_list_get_only_without_new_evidence(self):
        calls = []
        def list_messages(**request):
            calls.append(("list", request))
            return {"messages": [{"id": "fabricated-a", "threadId": "fabricated-t"}, {"id": "fabricated-b", "threadId": "fabricated-t"}]}
        def get_message(**request):
            calls.append(("get", request))
            return {"id": request["message_id"], "threadId": "fabricated-t", "labelIds": ["SENT"],
                    "payload": {"filename": "sample.bin", "body": {"size": 12}}}
        reader = GmailReader(query="larger:1M", list_messages=list_messages, get_message=get_message, granted_scopes=GMAIL_SCOPES)
        output = StringIO()
        with patch.object(gmail_cli, "load_credentials", return_value=object()), patch.object(gmail_cli, "build_google_reader", return_value=reader), patch("socket.socket", side_effect=AssertionError("network")), redirect_stdout(output):
            status = gmail_cli.main(["--query", "larger:1M", "--max-pages", "1", "--client-secrets", "unused", "--token", "unused", "--duplicates"])
        self.assertEqual(status, 0)
        self.assertEqual([kind for kind, _ in calls], ["list", "get", "get"])
        self.assertIn("authority: unresolved", output.getvalue())
        self.assertNotIn("fabricated-", output.getvalue())
        self.assertNotIn("same_thread_original_forward:", output.getvalue())
        self.assertNotIn("self_sent_copy_pattern", output.getvalue())


if __name__ == "__main__":
    unittest.main()
