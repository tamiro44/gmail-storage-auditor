"""Explicit, approval-gated quarantine action over policy-selected candidates.

This module deliberately has no discovery or deletion capability. Provider message
identifiers remain inside the adapter; every public result uses run-local refs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

QUARANTINE_LABEL_NAME = "quarentine"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_QUARANTINE_SCOPES = (GMAIL_MODIFY_SCOPE,)
# These optional OpenID Connect scopes support account identity binding only.
# They do not grant Gmail access and are not needed to mutate a message.
QUARANTINE_IDENTITY_SCOPES = frozenset(("openid", "email"))
LABEL_LIST_FIELDS = "labels(id,name,type)"


def _refs(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise QuarantineError(f"{field}_required")
    if any(not isinstance(ref, str) or not ref.strip() for ref in value):
        raise QuarantineError(f"{field}_invalid")
    if len(set(value)) != len(value):
        raise QuarantineError(f"{field}_duplicate")
    return value


class QuarantineError(ValueError):
    """A fixed, privacy-safe quarantine failure code."""


def validate_quarantine_scopes(scopes: Iterable[str] | None) -> None:
    """Allow gmail.modify plus optional identity-only OpenID Connect scopes."""
    if scopes is None:
        raise QuarantineError("gmail_scope_missing")
    try:
        granted = set(scopes)
    except TypeError:
        raise QuarantineError("gmail_scope_invalid") from None
    if any(not isinstance(scope, str) for scope in granted):
        raise QuarantineError("gmail_scope_invalid")
    gmail_scopes = {
        scope for scope in granted
        if scope == "https://mail.google.com/"
        or scope.startswith("https://www.googleapis.com/auth/gmail.")
    }
    if gmail_scopes != {GMAIL_MODIFY_SCOPE}:
        raise QuarantineError("gmail_scope_not_strictly_modify")
    if granted - gmail_scopes - QUARANTINE_IDENTITY_SCOPES:
        raise QuarantineError("oauth_scope_not_allowed_for_quarantine")


@dataclass(frozen=True)
class CandidateSelection:
    """Exact refs already admitted by the project's candidate/safety policy."""

    refs: tuple[str, ...]
    retained_refs: tuple[str, ...]
    policy_version: str
    selection_revision: str

    def __post_init__(self) -> None:
        _refs(self.refs, "candidate_refs")
        _refs(self.retained_refs, "retained_refs")
        if set(self.refs) & set(self.retained_refs):
            raise QuarantineError("candidate_conflicts_with_retained_copy")
        for value, field in (
            (self.policy_version, "policy_version"),
            (self.selection_revision, "selection_revision"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise QuarantineError(f"{field}_required")


@dataclass(frozen=True)
class QuarantineApproval:
    """Current-interaction confirmation bound to one exact selection."""

    candidate_selection: CandidateSelection
    approved_refs: tuple[str, ...]
    interaction_ref: str
    action: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_selection, CandidateSelection):
            raise QuarantineError("candidate_selection_required")
        _refs(self.approved_refs, "approved_refs")
        if not set(self.approved_refs).issubset(self.candidate_selection.refs):
            raise QuarantineError("approval_outside_candidate_selection")
        if not isinstance(self.interaction_ref, str) or not self.interaction_ref.strip():
            raise QuarantineError("interaction_ref_required")
        if self.action != "apply_quarentine_label":
            raise QuarantineError("quarantine_action_not_confirmed")


@dataclass(frozen=True)
class QuarantineOutcome:
    ref: str
    success: bool
    reason: str | None = None


@dataclass(frozen=True)
class QuarantineResult:
    outcomes: tuple[QuarantineOutcome, ...]

    @property
    def quarantined_refs(self) -> tuple[str, ...]:
        return tuple(item.ref for item in self.outcomes if item.success)

    @property
    def failures(self) -> tuple[QuarantineOutcome, ...]:
        return tuple(item for item in self.outcomes if not item.success)


ListLabels = Callable[..., Mapping[str, Any]]
ModifyMessage = Callable[..., Mapping[str, Any]]


class GmailQuarantineAdapter:
    """Narrow adapter: list labels, then add one label to exact messages once."""

    def __init__(
        self,
        *,
        list_labels: ListLabels,
        modify_message: ModifyMessage,
        provider_ids_by_ref: Mapping[str, str],
        granted_scopes: Iterable[str],
        interaction_ref: str,
        active_selection: CandidateSelection,
        audit_mode: str = "interactive",
    ) -> None:
        validate_quarantine_scopes(granted_scopes)
        if not callable(list_labels) or not callable(modify_message):
            raise QuarantineError("quarantine_operations_required")
        if not isinstance(provider_ids_by_ref, Mapping):
            raise QuarantineError("private_reference_map_required")
        if any(
            not isinstance(ref, str) or not ref.strip()
            or not isinstance(provider_id, str) or not provider_id
            for ref, provider_id in provider_ids_by_ref.items()
        ):
            raise QuarantineError("private_reference_map_invalid")
        if not isinstance(interaction_ref, str) or not interaction_ref.strip():
            raise QuarantineError("interaction_ref_required")
        if not isinstance(active_selection, CandidateSelection):
            raise QuarantineError("active_candidate_selection_required")
        if audit_mode not in ("interactive", "scheduled"):
            raise QuarantineError("audit_mode_invalid")
        self._list_labels = list_labels
        self._modify_message = modify_message
        self._provider_ids_by_ref = dict(provider_ids_by_ref)
        self._interaction_ref = interaction_ref
        self._active_selection = active_selection
        self._audit_mode = audit_mode
        self._approval_consumed = False

    def apply(self, approval: QuarantineApproval) -> QuarantineResult:
        if not isinstance(approval, QuarantineApproval):
            raise QuarantineError("explicit_quarantine_approval_required")
        if self._audit_mode != "interactive":
            raise QuarantineError("scheduled_audit_is_report_only")
        if approval.interaction_ref != self._interaction_ref:
            raise QuarantineError("quarantine_approval_not_current")
        if approval.candidate_selection != self._active_selection:
            raise QuarantineError("candidate_selection_changed")
        if self._approval_consumed:
            raise QuarantineError("quarantine_approval_already_used")

        label_id = self._find_label()
        missing = [ref for ref in approval.approved_refs if ref not in self._provider_ids_by_ref]
        if missing:
            # Validate the complete exact selection before making the first change.
            raise QuarantineError("approved_reference_unavailable")

        outcomes: list[QuarantineOutcome] = []
        for ref in approval.approved_refs:
            if not self._approval_consumed:
                # Consume immediately before the first mutation attempt. Once a
                # provider call begins, its outcome may be uncertain and replay
                # must remain denied even when that call raises.
                self._approval_consumed = True
            try:
                response = self._modify_message(
                    user_id="me",
                    message_id=self._provider_ids_by_ref[ref],
                    add_label_ids=(label_id,),
                    remove_label_ids=(),
                )
                if not isinstance(response, Mapping):
                    raise TypeError
            except Exception:
                # No automatic retry: the provider may have applied the mutation.
                outcomes.append(QuarantineOutcome(ref, False, "label_application_failed"))
            else:
                outcomes.append(QuarantineOutcome(ref, True))
        return QuarantineResult(tuple(outcomes))

    def _find_label(self) -> str:
        try:
            response = self._list_labels(user_id="me", fields=LABEL_LIST_FIELDS)
            labels = response.get("labels") if isinstance(response, Mapping) else None
            if not isinstance(labels, list):
                raise TypeError
            matches = [
                label.get("id") for label in labels
                if isinstance(label, Mapping) and label.get("name") == QUARANTINE_LABEL_NAME
            ]
            if len(matches) != 1 or not isinstance(matches[0], str) or not matches[0]:
                raise QuarantineError("quarentine_label_not_found")
            return matches[0]
        except QuarantineError:
            raise
        except Exception:
            raise QuarantineError("gmail_label_lookup_failed") from None


def build_google_quarantine_adapter(
    *, credentials: Any, provider_ids_by_ref: Mapping[str, str], interaction_ref: str,
    active_selection: CandidateSelection, audit_mode: str = "interactive",
) -> GmailQuarantineAdapter:
    """Build a modify-only boundary; no delete/trash/archive operation is exposed."""
    scopes = _credential_scopes(credentials)
    validate_quarantine_scopes(scopes)
    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        labels = service.users().labels()
        messages = service.users().messages()
    except Exception:
        raise QuarantineError("gmail_client_initialization_failed") from None

    def list_labels(**request: Any) -> Mapping[str, Any]:
        return labels.list(
            userId=request["user_id"], fields=request["fields"]
        ).execute(num_retries=0)

    def modify_message(**request: Any) -> Mapping[str, Any]:
        return messages.modify(
            userId=request["user_id"],
            id=request["message_id"],
            body={
                "addLabelIds": list(request["add_label_ids"]),
                "removeLabelIds": list(request["remove_label_ids"]),
            },
        ).execute(num_retries=0)

    return GmailQuarantineAdapter(
        list_labels=list_labels,
        modify_message=modify_message,
        provider_ids_by_ref=provider_ids_by_ref,
        granted_scopes=scopes,
        interaction_ref=interaction_ref,
        active_selection=active_selection,
        audit_mode=audit_mode,
    )


def _credential_scopes(credentials: Any) -> Iterable[str] | None:
    granted = getattr(credentials, "granted_scopes", None)
    return granted if granted is not None else getattr(credentials, "scopes", None)


def render_quarantine_result(result: QuarantineResult) -> str:
    """Render an auditable, provider-ID-free action summary."""
    if not isinstance(result, QuarantineResult):
        raise QuarantineError("quarantine_result_invalid")
    lines = ["# Quarantine result", "", "Applied label: quarentine", ""]
    for outcome in result.outcomes:
        status = "quarantined" if outcome.success else f"failed ({outcome.reason})"
        lines.append(f"- {outcome.ref}: {status}")
    return "\n".join(lines) + "\n"
