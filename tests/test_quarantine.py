"""Synthetic safety and request-spy tests for the quarantine boundary."""

import unittest

from gmail_storage_auditor.quarantine import (
    CandidateSelection,
    GMAIL_MODIFY_SCOPE,
    GmailQuarantineAdapter,
    QuarantineApproval,
    QuarantineError,
    render_quarantine_result,
    validate_quarantine_scopes,
)


class RequestSpy:
    def __init__(self, *, fail_ids=(), labels=None):
        self.calls = []
        self.fail_ids = set(fail_ids)
        self.labels = ([{"id": "Label_private", "name": "quarentine", "type": "user"}]
                       if labels is None else labels)

    def list_labels(self, **request):
        self.calls.append(("labels.list", request))
        return {"labels": self.labels}

    def modify_message(self, **request):
        self.calls.append(("messages.modify", request))
        if request["message_id"] in self.fail_ids:
            raise RuntimeError("synthetic provider detail must not escape")
        return {"id": request["message_id"], "labelIds": ["existing", "Label_private"]}


def selection(*refs):
    return CandidateSelection(tuple(refs), "0.1", "selection-1")


def approval(candidates, *refs, interaction="interaction-1"):
    return QuarantineApproval(
        candidates, tuple(refs), interaction, action="apply_quarentine_label"
    )


def adapter(spy, *, refs=("message-000001", "message-000002")):
    return GmailQuarantineAdapter(
        list_labels=spy.list_labels,
        modify_message=spy.modify_message,
        provider_ids_by_ref=dict(zip(refs, ("provider-a", "provider-b"))),
        granted_scopes=(GMAIL_MODIFY_SCOPE,),
        interaction_ref="interaction-1",
    )


class QuarantineSafetyTests(unittest.TestCase):
    def test_explicit_current_confirmation_and_policy_selection_are_required(self):
        spy = RequestSpy()
        target = adapter(spy)
        for invalid in (None, True, ("message-000001",)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(QuarantineError):
                    target.apply(invalid)
        self.assertEqual(spy.calls, [])

        candidates = selection("message-000001")
        with self.assertRaises(QuarantineError):
            approval(candidates, "message-000002")
        with self.assertRaises(QuarantineError):
            target.apply(approval(candidates, "message-000001", interaction="old-interaction"))
        with self.assertRaisesRegex(QuarantineError, "quarantine_action_not_confirmed"):
            QuarantineApproval(
                candidates, ("message-000001",), "interaction-1", action="analyze"
            )
        self.assertEqual(spy.calls, [])

    def test_request_spy_sees_only_label_lookup_and_additive_message_modify(self):
        spy = RequestSpy()
        candidates = selection("message-000001", "message-000002")
        result = adapter(spy).apply(approval(candidates, "message-000002"))

        self.assertEqual(result.quarantined_refs, ("message-000002",))
        self.assertEqual(spy.calls, [
            ("labels.list", {"user_id": "me", "fields": "labels(id,name,type)"}),
            ("messages.modify", {
                "user_id": "me", "message_id": "provider-b",
                "add_label_ids": ("Label_private",), "remove_label_ids": (),
            }),
        ])
        forbidden = {"trash", "delete", "archive", "mark_read", "thread", "create_label"}
        self.assertTrue(forbidden.isdisjoint(name for name, _ in spy.calls))

    def test_missing_expected_label_fails_closed_without_creation_or_modify(self):
        for labels in ([], [{"id": "other", "name": "quarantine"}]):
            with self.subTest(labels=labels):
                spy = RequestSpy(labels=labels)
                with self.assertRaisesRegex(QuarantineError, "quarentine_label_not_found"):
                    adapter(spy).apply(approval(selection("message-000001"), "message-000001"))
                self.assertEqual([name for name, _ in spy.calls], ["labels.list"])

    def test_all_refs_resolve_before_first_mutation(self):
        spy = RequestSpy()
        target = adapter(spy, refs=("message-000001",))
        candidates = selection("message-000001", "message-000002")
        with self.assertRaisesRegex(QuarantineError, "approved_reference_unavailable"):
            target.apply(approval(candidates, "message-000001", "message-000002"))
        self.assertEqual([name for name, _ in spy.calls], ["labels.list"])

    def test_partial_failures_are_explicit_not_retried_and_hide_provider_ids(self):
        spy = RequestSpy(fail_ids=("provider-a",))
        candidates = selection("message-000001", "message-000002")
        result = adapter(spy).apply(approval(candidates, *candidates.refs))
        report = render_quarantine_result(result)

        self.assertEqual([name for name, _ in spy.calls].count("messages.modify"), 2)
        self.assertEqual(result.quarantined_refs, ("message-000002",))
        self.assertEqual(result.failures[0].reason, "label_application_failed")
        self.assertIn("message-000001: failed (label_application_failed)", report)
        self.assertIn("message-000002: quarantined", report)
        self.assertNotIn("provider-a", report)
        self.assertNotIn("provider-b", report)
        self.assertNotIn("synthetic provider detail", report)

    def test_scope_is_minimal_and_broad_or_readonly_scopes_are_rejected(self):
        validate_quarantine_scopes((GMAIL_MODIFY_SCOPE, "openid"))
        for scopes in (
            ("https://www.googleapis.com/auth/gmail.readonly",),
            ("https://www.googleapis.com/auth/gmail.labels",),
            ("https://mail.google.com/",),
            (GMAIL_MODIFY_SCOPE, "https://www.googleapis.com/auth/gmail.send"),
        ):
            with self.subTest(scopes=scopes):
                with self.assertRaises(QuarantineError):
                    validate_quarantine_scopes(scopes)


if __name__ == "__main__":
    unittest.main()
