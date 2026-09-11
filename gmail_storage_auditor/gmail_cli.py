"""Interactive local entry point for a bounded, read-only Gmail inventory."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from .gmail import (
    GMAIL_SCOPES,
    GmailConnectorError,
    build_google_reader,
    validate_gmail_scopes,
)
from .inventory import InventoryError, Scope, collect_inventory
from .report import render_inventory
from .duplicates import analyze_duplicates
from .duplicate_report import render_duplicates


def _outside_repository(path_text: str, *, must_exist: bool) -> Path:
    path = Path(path_text).expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if path == repository or repository in path.parents:
        raise GmailConnectorError("credential_path_inside_repository")
    if must_exist and not path.is_file():
        raise GmailConnectorError("credential_file_missing")
    return path


def _scopes_from_token_file(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scopes = payload.get("scopes")
        if isinstance(scopes, str):
            return tuple(scopes.split())
        if isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes):
            return tuple(scopes)
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        pass
    raise GmailConnectorError("token_file_invalid")


def load_credentials(*, client_secrets_path: str, token_path: str) -> Any:
    """Load/refresh or interactively create a token outside the repository."""
    secrets = _outside_repository(client_secrets_path, must_exist=True)
    token = _outside_repository(token_path, must_exist=False)
    if secrets == token:
        raise GmailConnectorError("credential_paths_must_differ")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise GmailConnectorError("gmail_dependencies_missing") from None

    credentials = None
    if token.exists():
        validate_gmail_scopes(_scopes_from_token_file(token))
        try:
            credentials = Credentials.from_authorized_user_file(str(token), GMAIL_SCOPES)
        except Exception:
            raise GmailConnectorError("token_file_invalid") from None
        validate_gmail_scopes(_credential_scopes(credentials))

    if credentials is not None and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:
            raise GmailConnectorError("gmail_token_refresh_failed") from None
        validate_gmail_scopes(_credential_scopes(credentials))

    if credentials is None or not credentials.valid:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets), GMAIL_SCOPES)
            credentials = flow.run_local_server(port=0)
        except Exception:
            raise GmailConnectorError("gmail_oauth_failed") from None
        validate_gmail_scopes(_credential_scopes(credentials))
        try:
            token.write_text(credentials.to_json(), encoding="utf-8")
            try:
                os.chmod(token, 0o600)
            except OSError:
                pass
        except OSError:
            raise GmailConnectorError("token_file_write_failed") from None
    return credentials


def _credential_scopes(credentials: Any) -> Any:
    granted = getattr(credentials, "granted_scopes", None)
    return granted if granted is not None else getattr(credentials, "scopes", None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a targeted read-only Gmail storage inventory.")
    parser.add_argument("--query", required=True, help="Explicit Gmail search query, for example larger:10M")
    parser.add_argument("--max-pages", required=True, type=int, help="Positive finite Gmail page limit")
    parser.add_argument("--client-secrets", required=True, help="OAuth desktop-client JSON outside this repository")
    parser.add_argument("--token", required=True, help="OAuth token JSON outside this repository")
    parser.add_argument("--duplicates", action="store_true", help="Append analysis-only duplicate metadata report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.query.strip():
        print("Gmail inventory failed: gmail_query_required", file=sys.stderr)
        return 2
    if args.max_pages < 1:
        print("Gmail inventory failed: gmail_page_limit_invalid", file=sys.stderr)
        return 2
    try:
        credentials = load_credentials(
            client_secrets_path=args.client_secrets, token_path=args.token
        )
        reader = build_google_reader(credentials=credentials, query=args.query)
        scope = Scope(f"Gmail query: {args.query}")
        inventory = collect_inventory(
            reader,
            scope,
            as_of=datetime.now(timezone.utc),
            max_pages=args.max_pages,
        )
        report = render_duplicates(analyze_duplicates(inventory)) if args.duplicates else render_inventory(inventory)
        print(report, end="")
        return 0
    except (GmailConnectorError, InventoryError) as error:
        print(f"Gmail inventory failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
