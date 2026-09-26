"""Synthetic regression tests for the human-controlled quarantine CLI."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gmail_storage_auditor.duplicates import analyze_duplicates
from gmail_storage_auditor.gmail import GMAIL_READONLY_SCOPE, GmailConnectorError, GmailReader
from gmail_storage_auditor.gmail_quarantine_cli import (
    CONFIRMATION_TEXT,
    _parser,
    main,
    run_workflow,
)
from gmail_storage_auditor.inventory import Attachment, Hint, Inventory, Message, Scope
from gmail_storage_auditor.quarantine import GMAIL_MODIFY_SCOPE, QuarantineError, QuarantineResult, QuarantineOutcome
from gmail_storage_auditor.risk import classify_risk
from gmail_storage_auditor.scoring import score_cleanup


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
CANARY = "SYNTHETIC_PROVIDER_PRIVATE_CANARY"


def plan_fixture():
    attachment = (Attachment("fabricated.bin", 100),)
    messages = (
        Message("message-000001", 1000, AS_OF, "thread-000001", "received", attachment, True,
                (Hint("original", "synthetic fixture"),)),
        Message("message-000002", 800, AS_OF, "thread-000001", "sent", attachment, True,
                (Hint("forwarded", "synthetic fixture"),)),
    )
    inventory = Inventory(Scope("fabricated", synthetic=True), AS_OF, messages, True, None, 1)
    duplicates = analyze_duplicates(inventory)
    return score_cleanup(duplicates, classify_risk(inventory, duplicates))


class FakeAdapter:
    def __init__(self):
        self.approvals = []

    def apply(self, approval):
        self.approvals.append(approval)
        return QuarantineResult(tuple(QuarantineOutcome(ref, True) for ref in approval.approved_refs))


class GmailQuarantineCliTests(unittest.TestCase):
    def args(self, directory):
        base = Path(directory)
        values = [
            "--query", "larger:10M older:1y", "--max-pages", "1",
            "--candidate-limit", "2", "--client-secrets", str(base / "read-client.json"),
            "--token", str(base / "read-token.json"),
            "--modify-client-secrets", str(base / "modify-client.json"),
            "--modify-token", str(base / "modify-token.json"),
        ]
        return _parser().parse_args(values)

    def reader(self):
        reader = GmailReader(
            query="larger:10M older:1y", list_messages=lambda **_: {},
            get_message=lambda **_: {}, granted_scopes=(GMAIL_READONLY_SCOPE,),
        )
        reader._message_refs = {
            "provider-retained": "message-000001",
            "provider-selected": "message-000002",
        }
        return reader

    def test_inventory_and_recommendations_precede_modify_credentials_and_adapter(self):
        events = []
        prompt_texts = []
        plan = plan_fixture()
        adapter = FakeAdapter()
        prompts = iter(("message-000002", CONFIRMATION_TEXT))
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.load_credentials",
                  side_effect=lambda **_: events.append("readonly_credentials") or object()))
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.build_google_reader",
                  side_effect=lambda **_: events.append("reader") or self.reader()))
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.collect_inventory",
                  side_effect=lambda *a, **k: events.append("inventory") or plan.duplicates.inventory))
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.load_modify_credentials",
                  side_effect=lambda **_: events.append("modify_credentials") or object()))
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.build_google_quarantine_adapter",
                  side_effect=lambda **_: events.append("adapter") or adapter))
            output = StringIO()
            with redirect_stdout(output):
                code = run_workflow(
                    self.args(directory),
                    prompt=lambda text: prompt_texts.append(text) or events.append(
                        "confirmation" if text.startswith("Type") else "selection"
                    ) or next(prompts),
                    now=lambda: AS_OF,
                )

        self.assertEqual(code, 0)
        self.assertLess(events.index("inventory"), events.index("selection"))
        self.assertLess(events.index("selection"), events.index("confirmation"))
        self.assertLess(events.index("confirmation"), events.index("modify_credentials"))
        self.assertLess(events.index("modify_credentials"), events.index("adapter"))
        self.assertIn("## Review", output.getvalue())
        self.assertIn("Eligible quarantine candidates: message-000002", output.getvalue())
        self.assertNotIn("provider-selected", output.getvalue())
        self.assertEqual(adapter.approvals[0].approved_refs, ("message-000002",))
        self.assertEqual(adapter.approvals[0].action, "apply_quarentine_label")
        confirmation_prompt = prompt_texts[-1]
        self.assertIn("existing `quarentine` label", confirmation_prompt)
        self.assertIn("does not delete messages or recover storage", confirmation_prompt)

    def test_cancel_eof_empty_unknown_or_wrong_confirmation_never_loads_modify_credentials(self):
        plan = plan_fixture()
        cases = (
            (iter(("",)), "candidate_selection_empty"),
            (iter(("message-999999",)), "candidate_selection_unknown"),
            (iter(("message-000002", "yes")), "quarantine_cancelled"),
        )
        for answers, reason in cases:
            with self.subTest(reason=reason):
                with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                    stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.load_credentials", return_value=object()))
                    stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.build_google_reader", return_value=self.reader()))
                    stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.collect_inventory", return_value=plan.duplicates.inventory))
                    modify = stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.load_modify_credentials"))
                    with redirect_stdout(StringIO()), self.assertRaisesRegex(ValueError, reason):
                        run_workflow(self.args(directory), prompt=lambda _: next(answers), now=lambda: AS_OF)
                    modify.assert_not_called()

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.load_credentials", return_value=object()))
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.build_google_reader", return_value=self.reader()))
            stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.collect_inventory", return_value=plan.duplicates.inventory))
            modify = stack.enter_context(patch("gmail_storage_auditor.gmail_quarantine_cli.load_modify_credentials"))
            with redirect_stdout(StringIO()), self.assertRaises(EOFError):
                run_workflow(self.args(directory), prompt=lambda _: (_ for _ in ()).throw(EOFError()), now=lambda: AS_OF)
            modify.assert_not_called()

    def test_limits_and_distinct_credentials_fail_before_authentication(self):
        with patch("gmail_storage_auditor.gmail_quarantine_cli.run_workflow") as workflow:
            for option, value, reason in (
                ("--max-pages", "0", "gmail_page_limit_not_small"),
                ("--max-pages", "4", "gmail_page_limit_not_small"),
                ("--candidate-limit", "0", "candidate_limit_not_small"),
                ("--candidate-limit", "11", "candidate_limit_not_small"),
            ):
                with self.subTest(option=option, value=value), tempfile.TemporaryDirectory() as directory:
                    argv = vars(self.args(directory))
                    argv[option[2:].replace("-", "_")] = value
                    command = []
                    for key, item in argv.items():
                        command.extend(("--" + key.replace("_", "-"), str(item)))
                    stderr = StringIO()
                    with redirect_stderr(stderr):
                        self.assertEqual(main(command), 2)
                    self.assertIn(reason, stderr.getvalue())
            workflow.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            args = self.args(directory)
            args.modify_token = args.token
            with patch("gmail_storage_auditor.gmail_quarantine_cli.load_credentials") as load:
                with self.assertRaisesRegex(GmailConnectorError, "credential_paths_must_be_distinct"):
                    run_workflow(args, now=lambda: AS_OF)
                load.assert_not_called()

    def test_default_readonly_cli_does_not_import_quarantine_workflow(self):
        source = (Path(__file__).resolve().parents[1] / "gmail_storage_auditor" / "gmail_cli.py").read_text(encoding="utf-8")
        self.assertNotIn("gmail_quarantine_cli", source)
        self.assertNotIn("build_google_quarantine_adapter", source)

    def test_main_hides_raw_provider_failure_and_eof_cancels(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = []
            for key, value in vars(self.args(directory)).items():
                argv.extend(("--" + key.replace("_", "-"), str(value)))
            for failure, expected in (
                (QuarantineError("fixed_safe_code"), "fixed_safe_code"),
                (EOFError(), "no mailbox changes requested"),
            ):
                with self.subTest(expected=expected), patch(
                    "gmail_storage_auditor.gmail_quarantine_cli.run_workflow", side_effect=failure
                ):
                    stderr = StringIO()
                    with redirect_stderr(stderr):
                        self.assertEqual(main(argv), 1)
                    self.assertIn(expected, stderr.getvalue())
                    self.assertNotIn(CANARY, stderr.getvalue())

    def test_modify_loader_requests_only_modify_scope(self):
        from gmail_storage_auditor.quarantine import GMAIL_QUARANTINE_SCOPES
        self.assertEqual(GMAIL_QUARANTINE_SCOPES, (GMAIL_MODIFY_SCOPE,))


if __name__ == "__main__":
    unittest.main()
