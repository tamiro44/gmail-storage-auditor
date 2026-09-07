"""GSA-002 acceptance evidence using invented metadata and read-only sources."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import traceback
import unittest
from unittest.mock import patch

from gmail_storage_auditor import demo
from gmail_storage_auditor.inventory import (
    Attachment,
    Hint,
    InventoryError,
    Message,
    Page,
    Scope,
    collect_inventory,
)
from gmail_storage_auditor.report import render_inventory


MIB = 1024 * 1024
AS_OF = datetime(2026, 9, 7, tzinfo=timezone.utc)
SCOPE = Scope("Synthetic selected messages", synthetic=True)
CANARY = "SYNTHETIC_PRIVATE_ERROR_CANARY"


class RecordingReader:
    """Only read_page is usable; the other methods detect forbidden calls."""

    def __init__(self, pages):
        self.pages = pages
        self.reads = []
        self.mutation_attempts = []

    def read_page(self, scope, cursor):
        self.reads.append((scope, cursor))
        page = self.pages[cursor]
        if isinstance(page, Exception):
            raise page
        return page

    def _mutation(self, *args, **kwargs):
        self.mutation_attempts.append((args, kwargs))
        raise AssertionError("Inventory attempted a mutation")

    trash = _mutation
    delete = _mutation
    modify = _mutation
    add_label = _mutation
    remove_label = _mutation
    mark_read = _mutation
    mark_unread = _mutation


def inventory_for(*messages, scope=SCOPE):
    reader = RecordingReader({None: Page(tuple(messages), complete=True)})
    return collect_inventory(reader, scope, as_of=AS_OF, max_pages=1)


class InventoryCollectionTests(unittest.TestCase):
    def test_paginated_known_totals_count_identity_once_and_ignore_attachment_bytes(self):
        large = Message(
            "synthetic-large",
            size_estimate_bytes=12 * MIB,
            attachments=(Attachment("synthetic-large.bin", 10 * MIB),),
            attachments_complete=True,
        )
        small = Message("synthetic-small", size_estimate_bytes=4 * MIB)
        unknown = Message("synthetic-unknown")
        reader = RecordingReader({
            None: Page((large, unknown), next_cursor="synthetic-page-2"),
            "synthetic-page-2": Page((large, small), complete=True),
        })

        result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=2)

        self.assertEqual(result.message_count, 3)
        self.assertEqual(result.known_estimated_bytes, 16 * MIB)
        self.assertEqual(result.unknown_size_count, 1)
        self.assertEqual(result.messages, (large, small, unknown))
        self.assertEqual(result.pages_read, 2)
        self.assertTrue(result.complete)
        self.assertIsNone(result.partial_reason)
        self.assertEqual(reader.reads, [(SCOPE, None), (SCOPE, "synthetic-page-2")])
        report = render_inventory(result)
        self.assertIn("Unique observed messages: 3", report)
        self.assertIn("Known whole-message size estimates (observed records only): 16,777,216 bytes", report)
        self.assertIn("Messages with unknown size: 1", report)
        self.assertEqual(reader.mutation_attempts, [])

    def test_equal_metadata_at_distinct_references_remains_two_observations(self):
        attachment = Attachment("synthetic-copy.bin", MIB)
        first = Message(
            "synthetic-a", size_estimate_bytes=4 * MIB,
            thread_ref="synthetic-thread", attachments=(attachment,),
        )
        second = Message(
            "synthetic-b", size_estimate_bytes=4 * MIB,
            thread_ref="synthetic-thread", attachments=(attachment,),
        )
        result = inventory_for(first, second)
        self.assertEqual(result.message_count, 2)
        self.assertEqual(result.known_estimated_bytes, 8 * MIB)

    def test_empty_and_all_unknown_have_different_storage_meaning(self):
        empty = inventory_for()
        unknown = inventory_for(Message("synthetic-unknown"))
        zero = inventory_for(Message("synthetic-zero", size_estimate_bytes=0))
        self.assertEqual((empty.message_count, empty.known_estimated_bytes), (0, 0))
        self.assertEqual(empty.unknown_size_count, 0)
        self.assertIsNone(unknown.known_estimated_bytes)
        self.assertEqual(unknown.unknown_size_count, 1)
        self.assertEqual(zero.known_estimated_bytes, 0)
        self.assertEqual(zero.unknown_size_count, 0)

    def test_sorting_is_known_size_descending_then_reference_with_unknown_last(self):
        messages = (
            Message("synthetic-unknown-z"),
            Message("synthetic-tie-b", size_estimate_bytes=4),
            Message("synthetic-largest", size_estimate_bytes=12),
            Message("synthetic-unknown-a"),
            Message("synthetic-tie-a", size_estimate_bytes=4),
        )
        first = inventory_for(*messages)
        second = inventory_for(*reversed(messages))
        self.assertEqual([message.ref for message in first.messages], [
            "synthetic-largest", "synthetic-tie-a", "synthetic-tie-b",
            "synthetic-unknown-a", "synthetic-unknown-z",
        ])
        self.assertEqual(first.messages, second.messages)
        self.assertEqual(render_inventory(first), render_inventory(second))

    def test_completed_targeted_scope_is_not_whole_mailbox_coverage(self):
        result = inventory_for(Message("synthetic-a"))
        self.assertTrue(result.complete)
        self.assertFalse(result.scope.whole_mailbox)
        self.assertIn("targeted scope only", render_inventory(result))
        self.assertIn("complete for requested scope", render_inventory(result))
        whole = inventory_for(scope=Scope("Synthetic entire mailbox", whole_mailbox=True, synthetic=True))
        self.assertTrue(whole.complete)
        self.assertTrue(whole.scope.whole_mailbox)
        self.assertNotEqual(render_inventory(result), render_inventory(whole))

    def test_page_limit_retains_observations_and_does_not_request_another_page(self):
        message = Message("synthetic-observed", size_estimate_bytes=7)
        reader = RecordingReader({None: Page((message,), next_cursor="synthetic-next")})
        result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=1)
        self.assertFalse(result.complete)
        self.assertEqual(result.partial_reason, "page_limit")
        self.assertEqual(result.messages, (message,))
        self.assertEqual(result.known_estimated_bytes, 7)
        self.assertEqual(len(reader.reads), 1)

    def test_repeated_cursor_stops_without_repeating_a_request(self):
        first = Message("synthetic-first", size_estimate_bytes=7)
        second = Message("synthetic-second", size_estimate_bytes=3)
        reader = RecordingReader({
            None: Page((first,), next_cursor="synthetic-loop"),
            "synthetic-loop": Page((second,), next_cursor="synthetic-loop"),
        })
        result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=5)
        self.assertFalse(result.complete)
        self.assertEqual(result.partial_reason, "repeated_cursor")
        self.assertEqual(result.message_count, 2)
        self.assertEqual(result.known_estimated_bytes, 10)
        self.assertEqual(len(reader.reads), 2)

    def test_reader_failure_after_success_preserves_data_and_sanitizes_error(self):
        message = Message("synthetic-observed", size_estimate_bytes=7)
        reader = RecordingReader({
            None: Page((message,), next_cursor="synthetic-failure"),
            "synthetic-failure": RuntimeError(CANARY),
        })
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=5)
            report = render_inventory(result)
        self.assertFalse(result.complete)
        self.assertEqual(result.partial_reason, "reader_failure")
        self.assertEqual(result.messages, (message,))
        self.assertEqual(len(reader.reads), 2)
        self.assertIn("partial", report.lower())
        self.assertNotIn(CANARY, report + stdout.getvalue() + stderr.getvalue())
        self.assertEqual(reader.mutation_attempts, [])

    def test_first_page_failure_is_partial_empty_inventory(self):
        reader = RecordingReader({None: RuntimeError(CANARY)})
        result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=2)
        self.assertFalse(result.complete)
        self.assertEqual(result.partial_reason, "reader_failure")
        self.assertEqual(result.message_count, 0)

    def test_source_error_and_unconfirmed_completion_are_partial(self):
        cases = (
            (Page((), failed=True), "reader_failure"),
            (Page((), complete=False), "source_incomplete"),
        )
        for page, reason in cases:
            with self.subTest(reason=reason):
                reader = RecordingReader({None: page})
                result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=2)
                self.assertFalse(result.complete)
                self.assertEqual(result.partial_reason, reason)
                self.assertIn("partial", render_inventory(result).lower())

    def test_failed_page_preserves_its_valid_observations(self):
        message = Message("synthetic-observed", size_estimate_bytes=7)
        reader = RecordingReader({None: Page((message,), failed=True)})
        result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=2)
        self.assertFalse(result.complete)
        self.assertEqual(result.partial_reason, "reader_failure")
        self.assertEqual(result.messages, (message,))
        self.assertEqual(result.known_estimated_bytes, 7)
        self.assertEqual(len(reader.reads), 1)


class InventoryValidationTests(unittest.TestCase):
    def test_missing_metadata_stays_explicitly_unknown(self):
        message = Message("synthetic-unknown")
        self.assertIsNone(message.size_estimate_bytes)
        self.assertIsNone(message.date)
        self.assertIsNone(message.thread_ref)
        self.assertIsNone(message.direction)
        self.assertEqual(message.attachments, ())
        self.assertIsNone(message.attachments_complete)
        self.assertEqual(message.hints, ())
        self.assertIsNone(Attachment().filename)
        self.assertIsNone(Attachment().size_bytes)

    def test_aware_dates_normalize_to_utc(self):
        local = datetime(2026, 9, 6, 2, 30, tzinfo=timezone(timedelta(hours=2)))
        message = Message("synthetic-dated", date=local)
        result = inventory_for(message)
        self.assertEqual(message.date, datetime(2026, 9, 6, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(message.date.utcoffset(), timedelta(0))
        self.assertEqual(result.as_of.utcoffset(), timedelta(0))
        self.assertIn("| 2026-09-06T00:30:00+00:00 | 0 |", render_inventory(result))

    def test_invalid_consumed_fields_fail_without_echoing_values(self):
        invalid_records = [
            lambda: Message(""),
            lambda: Message(" "),
            lambda: Message(123),
            lambda: Message("synthetic-a", size_estimate_bytes=-1),
            lambda: Message("synthetic-a", size_estimate_bytes=True),
            lambda: Message("synthetic-a", size_estimate_bytes=1.5),
            lambda: Message("synthetic-a", size_estimate_bytes=CANARY),
            lambda: Message("synthetic-a", date=CANARY),
            lambda: Message("synthetic-a", date=datetime(2026, 1, 1)),
            lambda: Message("synthetic-a", direction=CANARY),
            lambda: Message("synthetic-a", thread_ref=""),
            lambda: Message("synthetic-a", attachments=(CANARY,)),
            lambda: Message("synthetic-a", attachments=[]),
            lambda: Message("synthetic-a", attachments_complete=CANARY),
            lambda: Message("synthetic-a", hints=(CANARY,)),
            lambda: Attachment(size_bytes=-1),
            lambda: Attachment(size_bytes=True),
            lambda: Attachment(size_bytes=CANARY),
            lambda: Attachment(filename=123),
            lambda: Hint("", "synthetic-source"),
            lambda: Hint("forwarded", ""),
            lambda: Scope(""),
            lambda: Scope("synthetic", whole_mailbox=CANARY),
            lambda: Page((CANARY,), complete=True),
            lambda: Page((), next_cursor=123),
            lambda: Page((), complete=CANARY),
            lambda: Page((), complete=True, failed=True),
            lambda: Page((), next_cursor="synthetic-next", complete=True),
        ]
        for index, make_record in enumerate(invalid_records):
            with self.subTest(case=index):
                with self.assertRaises(InventoryError) as raised:
                    make_record()
                self.assertTrue(str(raised.exception))
                self.assertNotIn(CANARY, str(raised.exception))

    def test_invalid_scan_context_fails_before_reading(self):
        for bound in (0, -1, True, 1.5, CANARY):
            with self.subTest(bound=type(bound).__name__):
                reader = RecordingReader({})
                with self.assertRaises(InventoryError) as raised:
                    collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=bound)
                self.assertNotIn(CANARY, str(raised.exception))
                self.assertEqual(reader.reads, [])
        reader = RecordingReader({})
        with self.assertRaises(InventoryError):
            collect_inventory(reader, SCOPE, as_of=datetime(2026, 1, 1), max_pages=1)
        self.assertEqual(reader.reads, [])

    def test_future_date_fails_without_disclosing_the_observation(self):
        future = Message(CANARY, date=AS_OF + timedelta(seconds=1))
        with self.assertRaises(InventoryError) as raised:
            inventory_for(future)
        self.assertNotIn(CANARY, str(raised.exception))

    def test_conflicting_same_reference_fails_instead_of_selecting_one_version(self):
        first = Message(CANARY, size_estimate_bytes=1)
        conflicting = Message(CANARY, size_estimate_bytes=2)
        reader = RecordingReader({
            None: Page((first,), next_cursor="synthetic-next"),
            "synthetic-next": Page((conflicting,), complete=True),
        })
        with self.assertRaises(InventoryError) as raised:
            collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=2)
        self.assertNotIn(CANARY, str(raised.exception))

    def test_invalid_page_payload_is_validation_error_not_success(self):
        reader = RecordingReader({None: CANARY})
        with self.assertRaises(InventoryError) as raised:
            collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=1)
        self.assertNotIn(CANARY, str(raised.exception))

    def test_validation_error_from_reader_is_sanitized(self):
        reader = RecordingReader({None: InventoryError(CANARY)})
        with self.assertRaises(InventoryError) as raised:
            collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=1)
        self.assertNotIn(CANARY, str(raised.exception))
        self.assertNotIn(CANARY, "".join(traceback.format_exception(raised.exception)))


class InventoryReportTests(unittest.TestCase):
    def assert_inventory_only(self, report):
        for phrase in (
            "safe candidate", "cleanup score", "confidence:", "confidence %",
            "recommendation:", "retained copy:", "reclaimed bytes:",
            "recoverable bytes:", "savings:", "risk tier", "| keep |",
            "| review |", "| aggressive |", "| safe |",
        ):
            self.assertNotIn(phrase, report.lower())

    def test_report_presents_known_facts_and_hints_without_inference(self):
        message = Message(
            "synthetic-facts", size_estimate_bytes=12 * MIB,
            date=AS_OF - timedelta(days=800), direction="self_sent",
            thread_ref="synthetic-thread",
            attachments=(Attachment("synthetic-observation.bin", 4 * MIB), Attachment()),
            attachments_complete=False,
            hints=(Hint("forwarded", "synthetic-fixture"),),
        )
        report = render_inventory(inventory_for(message))
        for fact in ("synthetic-facts", "synthetic-observation.bin", "forwarded", "synthetic-fixture", "800"):
            self.assertIn(fact, report)
        self.assertIn("observ", report.lower())
        self.assertIn("synthetic", report.lower())
        self.assertIn("unknown", report.lower())
        self.assertIn("self_sent", report)
        self.assertIn("list partial", report)
        self.assertIn("Supplied observations", report)
        self.assert_inventory_only(report)

    def test_unknown_total_is_explicit_and_differs_from_empty_report(self):
        unknown_report = render_inventory(inventory_for(Message("synthetic-unknown")))
        empty_report = render_inventory(inventory_for())
        self.assertIn("Known whole-message size estimates (observed records only): unknown", unknown_report)
        self.assertIn("Known whole-message size estimates (observed records only): 0 bytes", empty_report)
        self.assertIn("Unique observed messages: 0", empty_report)
        self.assertNotEqual(unknown_report, empty_report)
        self.assert_inventory_only(unknown_report)
        self.assert_inventory_only(empty_report)

    def test_every_partial_reason_is_visible_in_output(self):
        readers_and_bounds = (
            (RecordingReader({None: Page((), next_cursor="synthetic-next")}), 1),
            (RecordingReader({None: Page(())}), 2),
            (RecordingReader({None: RuntimeError(CANARY)}), 2),
            (RecordingReader({
                None: Page((), next_cursor="synthetic-loop"),
                "synthetic-loop": Page((), next_cursor="synthetic-loop"),
            }), 3),
        )
        for reader, bound in readers_and_bounds:
            result = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=bound)
            with self.subTest(reason=result.partial_reason):
                report = render_inventory(result)
                self.assertIn("partial", report.lower())
                expected_reason = {
                    "page_limit": "page limit reached",
                    "source_incomplete": "source did not confirm completion",
                    "reader_failure": "reader failed",
                    "repeated_cursor": "source repeated a continuation cursor",
                }[result.partial_reason]
                self.assertIn(expected_reason, report)
                self.assertIn("observed records only", report)
                self.assertNotIn(CANARY, report)
                self.assert_inventory_only(report)

    def test_demo_runs_deterministically_with_network_blocked(self):
        outputs = []
        with (
            patch("socket.socket", side_effect=AssertionError("Network forbidden")) as socket_call,
            patch("socket.create_connection", side_effect=AssertionError("Network forbidden")) as connection_call,
            patch("socket.getaddrinfo", side_effect=AssertionError("Network forbidden")) as dns_call,
        ):
            for _ in range(2):
                output = StringIO()
                with redirect_stdout(output):
                    demo.main()
                outputs.append(output.getvalue())
            socket_call.assert_not_called()
            connection_call.assert_not_called()
            dns_call.assert_not_called()
        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(outputs[0].strip())
        self.assertIn("synthetic", outputs[0].lower())
        self.assertIn("forwarded", outputs[0].lower())
        self.assertIn("sent", outputs[0].lower())
        self.assertIn("unknown", outputs[0].lower())
        self.assertIn("Unique observed messages: 5", outputs[0])
        self.assertIn("Known whole-message size estimates (observed records only): 19,922,944 bytes", outputs[0])
        self.assertIn("Messages with unknown size: 1", outputs[0])
        self.assertIn("complete for requested scope", outputs[0])
        self.assertIn("targeted scope only", outputs[0])
        self.assert_inventory_only(outputs[0])


if __name__ == "__main__":
    unittest.main()
