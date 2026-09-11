"""Synthetic HTML snapshots and export boundary regressions."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from html import escape
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gmail_storage_auditor import gmail_cli
from gmail_storage_auditor.demo import AS_OF
from gmail_storage_auditor.duplicates import analyze_duplicates
from gmail_storage_auditor.html_report import render_html
from gmail_storage_auditor.inventory import Attachment, Hint, Inventory, Message, Scope


def examples():
    empty = Inventory(Scope("Synthetic empty", synthetic=True), AS_OF, (), True, None, 1)
    messages = (
        Message("original", 100, AS_OF, "thread", "received", (Attachment("sample & notes.txt", 12),), True,
                (Hint("original", "synthetic fixture"),)),
        Message("forward", None, None, "thread", "sent", (Attachment("sample & notes.txt", 12),), False,
                (Hint("forwarded", "synthetic fixture"),)),
        Message("unknown"),
    )
    partial = replace(empty, scope=Scope("Synthetic <selected>", synthetic=True), messages=messages,
                      complete=False, partial_reason="page_limit")
    return {"empty": empty, "partial_inventory": partial, "duplicates": analyze_duplicates(partial)}


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


class HtmlReportTests(unittest.TestCase):
    def test_snapshots_are_deterministic_without_network_or_file_access(self):
        for name, result in examples().items():
            expected = (Path(__file__).parent / "snapshots" / f"{name}.html").read_text(encoding="utf-8")
            with self.subTest(name=name), patch("socket.socket", side_effect=AssertionError("network")), patch("socket.create_connection", side_effect=AssertionError("network")), patch("socket.getaddrinfo", side_effect=AssertionError("network")), patch("builtins.open", side_effect=AssertionError("file I/O")):
                self.assertEqual(render_html(result), expected)
                self.assertEqual(render_html(result), expected)

    def test_all_derived_text_is_escaped_and_cannot_create_active_elements(self):
        payload = '<script src="https://invalid.example/"></script><img src=x onerror="alert(1)">&\' '
        base = examples()["partial_inventory"]
        item = Message(payload, attachments=(Attachment(payload, 1),), hints=(Hint(payload, payload),), thread_ref=payload)
        inventory = replace(base, scope=Scope(payload), messages=(item,))
        analysis = examples()["duplicates"]
        cluster = replace(analysis.clusters[0], filename=payload, members=(payload,), confidence=payload,
                          retained_ref=payload, retention_reason=payload, authority=payload,
                          evidence=(payload,), limitations=(payload,))
        report = render_html(replace(analysis, inventory=inventory, clusters=(cluster,), retained_refs=(payload,)))
        self.assertNotIn(payload, report)
        self.assertGreaterEqual(report.count(escape(payload, quote=True)), 13)
        parsed = Elements()
        parsed.feed(report)
        self.assertFalse(set(parsed.tags) & {"script", "img", "link", "iframe", "form", "object", "embed"})
        self.assertFalse(any(name in ("src", "href") or name.startswith("on") for name, _ in parsed.attributes))
        self.assertIn("default-src 'none'", report)

    def test_unknown_total_and_no_matches_are_not_zero_or_uniqueness_claims(self):
        inventory = replace(examples()["empty"], messages=(Message("unknown"),))
        report = render_html(analyze_duplicates(inventory))
        self.assertIn('<span>Known observed bytes</span><strong>unknown</strong>', report)
        self.assertIn("does not prove uniqueness", report)
        self.assertIn("Attachment enumeration is incomplete or unknown", report)

    def test_summary_cards_and_authority_states_are_presentational_only(self):
        report = render_html(examples()["duplicates"])
        self.assertEqual(report.count('<div class="card">'), 4)
        self.assertIn('<article class="authority source-supported">', report)
        self.assertIn('<span class="status">source_supported</span>', report)

        unresolved = examples()["duplicates"]
        cluster = replace(unresolved.clusters[0], authority="unresolved")
        report = render_html(replace(unresolved, clusters=(cluster,)))
        self.assertIn('<article class="authority unresolved">', report)
        self.assertIn('<span class="status">unresolved</span>', report)


class HtmlCliTests(unittest.TestCase):
    def run_cli(self, extras):
        stdout, stderr = StringIO(), StringIO()
        with patch.object(gmail_cli, "load_credentials", return_value=object()), patch.object(gmail_cli, "build_google_reader", return_value=object()), patch.object(gmail_cli, "collect_inventory", return_value=examples()["partial_inventory"]), redirect_stdout(stdout), redirect_stderr(stderr), patch("socket.socket", side_effect=AssertionError("network")):
            status = gmail_cli.main(["--query", "synthetic", "--max-pages", "1", "--client-secrets", "unused", "--token", "unused", *extras])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_optional_export_changes_no_console_output_and_creates_only_one_file(self):
        for duplicate_args in ([], ["--duplicates"]):
            with self.subTest(args=duplicate_args), TemporaryDirectory() as directory:
                target = Path(directory) / "report.html"
                baseline = self.run_cli(duplicate_args)
                actual = self.run_cli([*duplicate_args, "--html", str(target)])
                self.assertEqual(actual, baseline)
                self.assertEqual(actual[0], 0)
                self.assertEqual(list(Path(directory).iterdir()), [target])
                result = examples()["duplicates" if duplicate_args else "partial_inventory"]
                self.assertEqual(target.read_bytes(), render_html(result).encode("utf-8"))

    def test_bad_paths_fail_before_authentication_and_do_not_overwrite(self):
        with TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.html"
            existing.write_text("preserve", encoding="utf-8")
            for target in (existing, Path(directory) / "missing" / "report.html", Path(__file__).parent / "private.html"):
                with self.subTest(target=target), patch.object(gmail_cli, "load_credentials") as auth, redirect_stderr(StringIO()):
                    status = gmail_cli.main(["--query", "synthetic", "--max-pages", "1", "--client-secrets", "unused", "--token", "unused", "--html", str(target)])
                    self.assertEqual(status, 1)
                    auth.assert_not_called()
            self.assertEqual(existing.read_text(encoding="utf-8"), "preserve")

    def test_write_error_is_sanitized_and_console_report_is_preserved(self):
        with TemporaryDirectory() as directory:
            baseline = self.run_cli([])
            with patch.object(Path, "open", side_effect=OSError("SYNTHETIC_PRIVATE_PATH")):
                status, stdout, stderr = self.run_cli(["--html", str(Path(directory) / "report.html")])
            self.assertEqual(status, 1)
            self.assertEqual(stdout, baseline[1])
            self.assertEqual(stderr, "Gmail inventory failed: html_report_write_failed\n")


if __name__ == "__main__":
    unittest.main()
