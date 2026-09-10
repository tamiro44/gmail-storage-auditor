"""GSA-008 contract tests with fabricated Gmail responses and credentials."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import inspect
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from gmail_storage_auditor.gmail import (
    GMAIL_READONLY_SCOPE,
    GMAIL_SCOPES,
    LIST_FIELDS,
    MESSAGE_FIELDS,
    GmailConnectorError,
    GmailReader,
    build_google_reader,
    validate_gmail_scopes,
)
from gmail_storage_auditor.gmail_cli import _outside_repository, _scopes_from_token_file, main
from gmail_storage_auditor.inventory import InventoryError, Scope, collect_inventory
from gmail_storage_auditor.report import render_inventory


AS_OF = datetime(2026, 9, 8, tzinfo=timezone.utc)
SCOPE = Scope("Gmail query: larger:10M")
CANARY = "SYNTHETIC_PROVIDER_PRIVATE_CANARY"


class FakeGmailCalls:
    def __init__(self, pages, details):
        self.pages = pages
        self.details = details
        self.operations = []

    def list_messages(self, **request):
        self.operations.append(("users.messages.list", request))
        value = self.pages[request["page_token"]]
        if isinstance(value, Exception):
            raise value
        return value

    def get_message(self, **request):
        self.operations.append(("users.messages.get", request))
        value = self.details[request["message_id"]]
        if isinstance(value, Exception):
            raise value
        return value


def detail(
    message_id,
    thread_id,
    *,
    size="12582912",
    date="1788825600000",
    labels=None,
    payload=None,
    **extra,
):
    response = {
        "id": message_id,
        "threadId": thread_id,
        "sizeEstimate": size,
        "internalDate": date,
        "labelIds": [] if labels is None else labels,
    }
    if payload is not None:
        response["payload"] = payload
    response.update(extra)
    return response


def reader_for(calls, query="larger:10M", scopes=GMAIL_SCOPES):
    return GmailReader(
        query=query,
        list_messages=calls.list_messages,
        get_message=calls.get_message,
        granted_scopes=scopes,
    )


class GmailScopeTests(unittest.TestCase):
    def test_only_readonly_gmail_scope_is_accepted(self):
        validate_gmail_scopes(GMAIL_SCOPES)
        validate_gmail_scopes((GMAIL_READONLY_SCOPE, "openid"))
        rejected = (
            None,
            (),
            ("https://mail.google.com/",),
            ("https://www.googleapis.com/auth/gmail.modify",),
            (GMAIL_READONLY_SCOPE, "https://www.googleapis.com/auth/gmail.labels"),
            (GMAIL_READONLY_SCOPE, "https://www.googleapis.com/auth/gmail.send"),
        )
        for scopes in rejected:
            with self.subTest(scopes=scopes):
                with self.assertRaises(GmailConnectorError):
                    validate_gmail_scopes(scopes)

    def test_requested_scope_cannot_authorize_mutation(self):
        self.assertEqual(GMAIL_SCOPES, (GMAIL_READONLY_SCOPE,))
        combined = " ".join(GMAIL_SCOPES)
        for fragment in ("mail.google.com/", "gmail.modify", "gmail.labels", "gmail.send"):
            if fragment == "mail.google.com/":
                self.assertNotIn("https://mail.google.com/", combined)
            else:
                self.assertNotIn(fragment, combined)

    def test_token_scope_file_validation_rejects_broad_scope_without_google_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "synthetic-token.json"
            token.write_text(json.dumps({"scopes": [GMAIL_READONLY_SCOPE]}), encoding="utf-8")
            self.assertEqual(_scopes_from_token_file(token), GMAIL_SCOPES)
            token.write_text(json.dumps({"scopes": ["https://mail.google.com/"]}), encoding="utf-8")
            with self.assertRaises(GmailConnectorError):
                validate_gmail_scopes(_scopes_from_token_file(token))

    def test_repository_credential_paths_are_refused(self):
        repository_path = Path(__file__).resolve().parents[1] / "synthetic-token.json"
        with self.assertRaises(GmailConnectorError):
            _outside_repository(str(repository_path), must_exist=False)


class GmailReaderTests(unittest.TestCase):
    def test_google_client_is_hidden_behind_list_and_get_only(self):
        operations = []

        class Request:
            def __init__(self, response):
                self.response = response

            def execute(self, **kwargs):
                operations.append(("execute", kwargs))
                return self.response

        class MessagesResource:
            def list(self, **kwargs):
                operations.append(("users.messages.list", kwargs))
                return Request({"messages": [{"id": "provider-a", "threadId": "provider-t"}]})

            def get(self, **kwargs):
                operations.append(("users.messages.get", kwargs))
                return Request(detail("provider-a", "provider-t"))

            def trash(self, **kwargs):
                raise AssertionError("mutation method must never be called")

        resource = MessagesResource()

        class Service:
            def users(self):
                return self

            def messages(self):
                return resource

        discovery = types.ModuleType("googleapiclient.discovery")

        def fake_build(*args, **kwargs):
            operations.append(("build", (args, kwargs)))
            return Service()

        discovery.build = fake_build
        package = types.ModuleType("googleapiclient")
        package.discovery = discovery

        class Credentials:
            granted_scopes = GMAIL_SCOPES
            scopes = GMAIL_SCOPES

        with patch.dict(sys.modules, {
            "googleapiclient": package,
            "googleapiclient.discovery": discovery,
        }):
            reader = build_google_reader(credentials=Credentials(), query="larger:10M")
            inventory = collect_inventory(reader, SCOPE, as_of=AS_OF, max_pages=1)

        named_operations = [name for name, _ in operations]
        self.assertEqual(
            named_operations,
            ["build", "users.messages.list", "execute", "users.messages.get", "execute"],
        )
        self.assertTrue(inventory.complete)
        list_request = operations[1][1]
        get_request = operations[3][1]
        self.assertEqual(list_request["userId"], "me")
        self.assertEqual(list_request["q"], "larger:10M")
        self.assertEqual(list_request["fields"], LIST_FIELDS)
        self.assertEqual(get_request["userId"], "me")
        self.assertEqual(get_request["format"], "metadata")
        self.assertEqual(get_request["fields"], MESSAGE_FIELDS)
        self.assertEqual(operations[2][1], {"num_retries": 0})
        self.assertEqual(operations[4][1], {"num_retries": 0})

    def test_paginated_metadata_feeds_existing_inventory_and_uses_only_list_get(self):
        pages = {
            None: {
                "messages": [{"id": "provider-a", "threadId": "provider-thread"}],
                "nextPageToken": "provider-next-token",
            },
            "provider-next-token": {
                "messages": [
                    {"id": "provider-a", "threadId": "provider-thread"},
                    {"id": "provider-b", "threadId": "provider-thread-b"},
                ]
            },
        }
        nested_payload = {
            "parts": [{
                "parts": [{"filename": "synthetic-large.bin", "body": {"size": 4 * 1024 * 1024}}]
            }]
        }
        details = {
            "provider-a": detail(
                "provider-a", "provider-thread", labels=["SENT"], payload=nested_payload
            ),
            "provider-b": detail("provider-b", "provider-thread-b", size=None, date=None),
        }
        calls = FakeGmailCalls(pages, details)
        inventory = collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=2)

        self.assertTrue(inventory.complete)
        self.assertEqual(inventory.message_count, 2)
        self.assertEqual(inventory.known_estimated_bytes, 12 * 1024 * 1024)
        self.assertEqual(inventory.unknown_size_count, 1)
        self.assertEqual(inventory.messages[0].ref, "message-000001")
        self.assertEqual(inventory.messages[0].thread_ref, "thread-000001")
        self.assertEqual(inventory.messages[0].direction, "sent")
        self.assertEqual(inventory.messages[0].attachments[0].filename, "synthetic-large.bin")
        self.assertEqual(inventory.messages[0].attachments[0].size_bytes, 4 * 1024 * 1024)
        self.assertFalse(inventory.messages[0].attachments_complete)
        self.assertNotIn("provider-a", render_inventory(inventory))
        self.assertNotIn("provider-thread", render_inventory(inventory))
        self.assertEqual(
            [operation for operation, _ in calls.operations],
            [
                "users.messages.list", "users.messages.get",
                "users.messages.list", "users.messages.get", "users.messages.get",
            ],
        )
        list_requests = [request for operation, request in calls.operations if operation.endswith("list")]
        self.assertIsNone(list_requests[0]["page_token"])
        self.assertEqual(list_requests[1]["page_token"], "provider-next-token")
        self.assertNotEqual(inventory.messages[0].ref, "provider-a")

    def test_request_fields_and_format_exclude_private_content(self):
        forbidden = ("raw", "snippet", "headers", "subject", "from", "to", "body(data)")
        self.assertEqual(LIST_FIELDS, "messages(id,threadId),nextPageToken")
        for value in forbidden:
            self.assertNotIn(value, MESSAGE_FIELDS.lower())

        calls = FakeGmailCalls(
            {None: {"messages": [{"id": "provider-a", "threadId": "provider-t"}]}},
            {"provider-a": detail("provider-a", "provider-t")},
        )
        collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=1)
        get_request = calls.operations[1][1]
        self.assertEqual(get_request["format"], "metadata")
        self.assertEqual(get_request["fields"], MESSAGE_FIELDS)
        self.assertNotIn("metadata_headers", get_request)

    def test_provider_private_fields_are_ignored_and_identifiers_stay_internal(self):
        calls = FakeGmailCalls(
            {None: {"messages": [{"id": "provider-a", "threadId": "provider-t"}]}},
            {"provider-a": detail(
                "provider-a", "provider-t", snippet=CANARY, raw=CANARY,
                payload={"headers": [{"name": "Subject", "value": CANARY}]},
            )},
        )
        inventory = collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=1)
        rendered = render_inventory(inventory)
        self.assertNotIn(CANARY, rendered)
        self.assertNotIn("provider-a", rendered)
        self.assertFalse(inventory.messages[0].attachments_complete)
        self.assertEqual(inventory.messages[0].attachments, ())

    def test_page_limit_and_provider_failure_use_existing_partial_semantics(self):
        calls = FakeGmailCalls(
            {
                None: {"messages": [{"id": "provider-a", "threadId": "provider-t"}], "nextPageToken": "secret-page"},
                "secret-page": RuntimeError(CANARY),
            },
            {"provider-a": detail("provider-a", "provider-t")},
        )
        limited = collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=1)
        self.assertEqual(limited.partial_reason, "page_limit")
        self.assertNotIn("secret-page", render_inventory(limited))

        calls = FakeGmailCalls(
            {
                None: {"messages": [{"id": "provider-a", "threadId": "provider-t"}], "nextPageToken": "secret-page"},
                "secret-page": RuntimeError(CANARY),
            },
            {"provider-a": detail("provider-a", "provider-t")},
        )
        failed = collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=2)
        self.assertEqual(failed.partial_reason, "reader_failure")
        self.assertEqual(failed.message_count, 1)
        self.assertNotIn(CANARY, render_inventory(failed))

    def test_repeated_provider_page_token_uses_existing_loop_detection(self):
        calls = FakeGmailCalls(
            {
                None: {"messages": [], "nextPageToken": "provider-loop"},
                "provider-loop": {"messages": [], "nextPageToken": "provider-loop"},
            },
            {},
        )
        inventory = collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=5)
        self.assertEqual(inventory.partial_reason, "repeated_cursor")
        self.assertEqual(len(calls.operations), 2)

    def test_malformed_values_fail_safely_without_provider_value(self):
        malformed = (
            {"messages": CANARY},
            {"messages": [{"id": CANARY, "threadId": "provider-t"}], "nextPageToken": 7},
        )
        for page in malformed:
            with self.subTest(page_fields=tuple(page)):
                calls = FakeGmailCalls({None: page}, {CANARY: detail(CANARY, "provider-t")})
                with self.assertRaises(InventoryError) as raised:
                    collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=1)
                self.assertNotIn(CANARY, str(raised.exception))

        bad_details = (
            detail("provider-a", "provider-t", size=-1),
            detail("provider-a", "provider-t", date="not-a-date"),
            detail("provider-a", "provider-t", labels=CANARY),
            detail("provider-a", "provider-t", payload={"parts": CANARY}),
        )
        for response in bad_details:
            with self.subTest(response_fields=tuple(response)):
                calls = FakeGmailCalls(
                    {None: {"messages": [{"id": "provider-a", "threadId": "provider-t"}]}},
                    {"provider-a": response},
                )
                with self.assertRaises(InventoryError) as raised:
                    collect_inventory(reader_for(calls), SCOPE, as_of=AS_OF, max_pages=1)
                self.assertNotIn(CANARY, str(raised.exception))

    def test_reader_has_no_public_mutation_or_generic_request_method(self):
        public_methods = {
            name for name, member in inspect.getmembers(GmailReader, inspect.isfunction)
            if not name.startswith("_")
        }
        self.assertEqual(public_methods, {"read_page"})
        for forbidden in ("trash", "delete", "modify", "label", "mark_read", "send", "draft", "request"):
            self.assertFalse(hasattr(GmailReader, forbidden))

    def test_real_reader_rejects_synthetic_or_whole_mailbox_scope(self):
        calls = FakeGmailCalls({}, {})
        reader = reader_for(calls)
        for scope in (Scope("synthetic", synthetic=True), Scope("whole", whole_mailbox=True)):
            with self.subTest(scope=scope.label):
                with self.assertRaises(InventoryError):
                    reader.read_page(scope, None)
        self.assertEqual(calls.operations, [])


class GmailCliTests(unittest.TestCase):
    def test_command_requires_query_and_positive_page_limit_before_authentication(self):
        with patch("gmail_storage_auditor.gmail_cli.load_credentials") as load:
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "--query", " ", "--max-pages", "1",
                    "--client-secrets", "outside.json", "--token", "token.json",
                ])
            self.assertEqual(code, 2)
            load.assert_not_called()

            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "--query", "larger:10M", "--max-pages", "0",
                    "--client-secrets", "outside.json", "--token", "token.json",
                ])
            self.assertEqual(code, 2)
            load.assert_not_called()

    def test_fake_cli_runs_existing_pipeline_without_network(self):
        calls = FakeGmailCalls(
            {None: {"messages": [{"id": "provider-a", "threadId": "provider-t"}]}},
            {"provider-a": detail("provider-a", "provider-t")},
        )
        fake_reader = reader_for(calls)
        with (
            patch("gmail_storage_auditor.gmail_cli.load_credentials", return_value=object()),
            patch("gmail_storage_auditor.gmail_cli.build_google_reader", return_value=fake_reader),
            patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network,
        ):
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "--query", "larger:10M", "--max-pages", "1",
                    "--client-secrets", "outside.json", "--token", "token.json",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("Gmail query: larger:10M", stdout.getvalue())
        self.assertNotIn("provider-a", stdout.getvalue())
        network.assert_not_called()

    def test_cli_sanitizes_connector_failure(self):
        with patch(
            "gmail_storage_auditor.gmail_cli.load_credentials",
            side_effect=GmailConnectorError("gmail_token_refresh_failed"),
        ):
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "--query", "larger:10M", "--max-pages", "1",
                    "--client-secrets", "outside.json", "--token", "token.json",
                ])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "Gmail inventory failed: gmail_token_refresh_failed\n")
        self.assertNotIn(CANARY, stderr.getvalue())

    def test_repository_contains_no_credential_json_artifact(self):
        repository = Path(__file__).resolve().parents[1]
        forbidden_names = (
            "token*.json", "credentials*.json", "client_secret*.json", "client-secrets*.json"
        )
        artifacts = []
        for pattern in forbidden_names:
            artifacts.extend(
                path for path in repository.glob(pattern) if path.is_file()
            )
        self.assertEqual(artifacts, [])


if __name__ == "__main__":
    unittest.main()
