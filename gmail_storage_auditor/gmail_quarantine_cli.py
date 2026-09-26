"""Human-controlled bounded Gmail audit-to-quarantine workflow."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any

from .cleanup_report import render_cleanup_report
from .duplicates import analyze_duplicates
from .gmail import GmailConnectorError, GmailReader, build_google_reader
from .gmail_cli import _credential_scopes, _outside_repository, load_credentials
from .inventory import InventoryError, Scope, collect_inventory
from .policy import PolicyError
from .quarantine import (
    GMAIL_QUARANTINE_SCOPES,
    CandidateSelection,
    QuarantineApproval,
    QuarantineError,
    build_google_quarantine_adapter,
    render_quarantine_result,
    validate_quarantine_scopes,
)
from .risk import classify_risk
from .scoring import CleanupPlan, score_cleanup


MAX_QUARANTINE_PAGES = 3
MAX_QUARANTINE_CANDIDATES = 10
CONFIRMATION_TEXT = "APPLY QUARENTINE LABEL"
_BROAD_LABELS = frozenset((
    "all", "all_mail", "anywhere", "inbox", "sent", "spam", "starred",
    "trash", "unread",
))
_SECONDARY_BOUND = re.compile(
    r"(?:^|\s)(?:after|before|filename|larger|newer|newer_than|older|"
    r"older_than|rfc822msgid|smaller):[^\s]+",
    flags=re.ASCII | re.IGNORECASE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a small Gmail scope and explicitly label selected recommendations."
    )
    parser.add_argument("--query", required=True, help="Explicit bounded Gmail search query")
    parser.add_argument("--max-pages", required=True, type=int, help="Page limit from 1 through 3")
    parser.add_argument("--candidate-limit", required=True, type=int, help="Candidate limit from 1 through 10")
    parser.add_argument("--client-secrets", required=True, help="Read-only OAuth client JSON outside this repository")
    parser.add_argument("--token", required=True, help="Read-only OAuth token JSON outside this repository")
    parser.add_argument("--modify-client-secrets", required=True, help="Separate modify OAuth client JSON outside this repository")
    parser.add_argument("--modify-token", required=True, help="Separate modify OAuth token JSON outside this repository")
    return parser


def _validate_credential_paths(args: argparse.Namespace) -> None:
    paths = tuple(
        _outside_repository(value, must_exist=False)
        for value in (
            args.client_secrets, args.token,
            args.modify_client_secrets, args.modify_token,
        )
    )
    if len(set(paths)) != len(paths):
        raise GmailConnectorError("credential_paths_must_be_distinct")


def _validate_bounded_query(query: object) -> None:
    """Require a dedicated label plus another narrowing predicate."""
    if not isinstance(query, str) or not query.strip():
        raise QuarantineError("gmail_query_required")
    labels = re.findall(
        r"(?:^|\s)label:([A-Za-z0-9_-]{1,64})(?=\s|$)", query,
        flags=re.ASCII | re.IGNORECASE,
    )
    custom_labels = tuple(
        label for label in labels if label.casefold() not in _BROAD_LABELS
    )
    if (not custom_labels or _SECONDARY_BOUND.search(query) is None
            or any(character in query for character in "\r\n{}")):
        raise QuarantineError("gmail_query_not_narrow_enough")


def _token_scopes(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scopes = payload.get("scopes")
        if isinstance(scopes, str):
            return tuple(scopes.split())
        if isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes):
            return tuple(scopes)
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        pass
    raise QuarantineError("modify_token_file_invalid")


def load_modify_credentials(*, client_secrets_path: str, token_path: str) -> Any:
    """Load/create only the separate, strictly gmail.modify credential."""
    secrets_path = _outside_repository(client_secrets_path, must_exist=True)
    token = _outside_repository(token_path, must_exist=False)
    if secrets_path == token:
        raise QuarantineError("modify_credential_paths_must_differ")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise QuarantineError("gmail_dependencies_missing") from None

    credentials = None
    if token.exists():
        validate_quarantine_scopes(_token_scopes(token))
        try:
            credentials = Credentials.from_authorized_user_file(
                str(token), GMAIL_QUARANTINE_SCOPES
            )
        except Exception:
            raise QuarantineError("modify_token_file_invalid") from None
        validate_quarantine_scopes(_credential_scopes(credentials))
    if credentials is not None and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:
            raise QuarantineError("modify_token_refresh_failed") from None
        validate_quarantine_scopes(_credential_scopes(credentials))
    if credentials is None or not credentials.valid:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_path), GMAIL_QUARANTINE_SCOPES
            )
            credentials = flow.run_local_server(port=0)
        except Exception:
            raise QuarantineError("modify_oauth_failed") from None
        validate_quarantine_scopes(_credential_scopes(credentials))
        try:
            token.write_text(credentials.to_json(), encoding="utf-8")
            try:
                os.chmod(token, 0o600)
            except OSError:
                pass
        except OSError:
            raise QuarantineError("modify_token_file_write_failed") from None
    return credentials


def verify_same_account(*, readonly_credentials: Any, modify_credentials: Any) -> None:
    """Compare account identities transiently without returning or logging them."""
    try:
        from googleapiclient.discovery import build

        identities = []
        for credentials in (readonly_credentials, modify_credentials):
            response = build(
                "gmail", "v1", credentials=credentials, cache_discovery=False
            ).users().getProfile(
                userId="me", fields="emailAddress"
            ).execute(num_retries=0)
            identity = response.get("emailAddress") if isinstance(response, Mapping) else None
            if not isinstance(identity, str) or not identity.strip():
                raise TypeError
            identities.append(identity.strip().casefold())
    except Exception:
        raise QuarantineError("gmail_account_verification_failed") from None
    if not hmac.compare_digest(*identities):
        raise QuarantineError("gmail_account_mismatch")


def _candidate_selection(plan: CleanupPlan, limit: int) -> CandidateSelection:
    eligible = tuple(
        candidate.message_ref for candidate in plan.candidates
        if candidate.recommendation in ("safe", "review", "aggressive")
    )[:limit]
    if not eligible:
        raise QuarantineError("no_eligible_recommended_candidates")
    retained = tuple(sorted(plan.duplicates.retained_refs))
    return CandidateSelection(
        eligible, retained, plan.policy_version,
        "selection-" + secrets.token_hex(8),
    )


def _read_selection(prompt: Callable[[str], str], candidates: CandidateSelection) -> tuple[str, ...]:
    raw = prompt("Select candidate references (comma-separated): ")
    refs = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not refs:
        raise QuarantineError("candidate_selection_empty")
    if len(set(refs)) != len(refs) or not set(refs).issubset(candidates.refs):
        raise QuarantineError("candidate_selection_unknown")
    return refs


def run_workflow(
    args: argparse.Namespace, *, prompt: Callable[[str], str] = input,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Run one interaction; dependencies remain patchable for synthetic tests."""
    _validate_bounded_query(args.query)
    _validate_credential_paths(args)
    readonly_credentials = load_credentials(
        client_secrets_path=args.client_secrets, token_path=args.token
    )
    reader = build_google_reader(credentials=readonly_credentials, query=args.query)
    inventory = collect_inventory(
        reader, Scope(f"Gmail query: {args.query}"),
        as_of=(now or (lambda: datetime.now(timezone.utc)))(),
        max_pages=args.max_pages,
    )
    if not inventory.complete:
        raise QuarantineError("gmail_query_exceeded_bounded_scan_narrow_query")
    duplicates = analyze_duplicates(inventory)
    plan = score_cleanup(duplicates, classify_risk(inventory, duplicates))
    print(render_cleanup_report(plan), end="")
    candidates = _candidate_selection(plan, args.candidate_limit)
    print("Eligible quarantine candidates: " + ", ".join(candidates.refs))
    selected = _read_selection(prompt, candidates)
    confirmation = prompt(
        "Type APPLY QUARENTINE LABEL to add the existing `quarentine` label "
        "to the selected messages. This does not delete messages or recover storage: "
    )
    if confirmation != CONFIRMATION_TEXT:
        raise QuarantineError("quarantine_cancelled")

    # Mutation-capable credentials and adapter are intentionally delayed until
    # inventory, recommendations, exact selection, and confirmation all finish.
    modify_credentials = load_modify_credentials(
        client_secrets_path=args.modify_client_secrets,
        token_path=args.modify_token,
    )
    verify_same_account(
        readonly_credentials=readonly_credentials,
        modify_credentials=modify_credentials,
    )
    if not isinstance(reader, GmailReader):
        raise QuarantineError("gmail_reader_state_unavailable")
    provider_map: Mapping[str, str] = reader._quarantine_reference_map()
    interaction_ref = "interaction-" + secrets.token_hex(8)
    approval = QuarantineApproval(
        candidates, selected, interaction_ref, "apply_quarentine_label"
    )
    adapter = build_google_quarantine_adapter(
        credentials=modify_credentials,
        provider_ids_by_ref=provider_map,
        interaction_ref=interaction_ref,
        active_selection=candidates,
    )
    print(render_quarantine_result(adapter.apply(approval)), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_bounded_query(args.query)
    except QuarantineError as error:
        print(f"Gmail quarantine failed: {error}", file=sys.stderr)
        return 2
    if not 1 <= args.max_pages <= MAX_QUARANTINE_PAGES:
        print("Gmail quarantine failed: gmail_page_limit_not_small", file=sys.stderr)
        return 2
    if not 1 <= args.candidate_limit <= MAX_QUARANTINE_CANDIDATES:
        print("Gmail quarantine failed: candidate_limit_not_small", file=sys.stderr)
        return 2
    try:
        return run_workflow(args)
    except (EOFError, KeyboardInterrupt):
        print("Gmail quarantine cancelled: no mailbox changes requested.", file=sys.stderr)
        return 1
    except (GmailConnectorError, InventoryError, QuarantineError, PolicyError) as error:
        print(f"Gmail quarantine failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
