"""Minimal Gmail metadata reader with no mailbox mutation surface."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .inventory import Attachment, InventoryError, Message, Page, Scope


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SCOPES = (GMAIL_READONLY_SCOPE,)

# List returns provider identifiers only. Get deliberately excludes snippets,
# headers, raw messages, and MIME body data.
LIST_FIELDS = "messages(id,threadId),nextPageToken"


def _message_part_fields(depth: int = 12) -> str:
    fields = "filename,body(size)"
    for _ in range(depth):
        fields = f"filename,body(size),parts({fields})"
    return fields


MESSAGE_FIELDS = (
    "id,threadId,labelIds,internalDate,sizeEstimate,"
    f"payload({_message_part_fields()})"
)


class GmailConnectorError(RuntimeError):
    """A fixed connector failure code safe to show without provider details."""


def validate_gmail_scopes(scopes: Iterable[str] | None) -> None:
    """Require readonly and reject every other Gmail-capable OAuth scope."""
    if scopes is None:
        raise GmailConnectorError("gmail_scope_missing")
    try:
        granted = set(scopes)
    except TypeError:
        raise GmailConnectorError("gmail_scope_invalid") from None
    if any(not isinstance(scope, str) for scope in granted):
        raise GmailConnectorError("gmail_scope_invalid")
    gmail_scopes = {
        scope
        for scope in granted
        if scope == "https://mail.google.com/"
        or scope.startswith("https://www.googleapis.com/auth/gmail.")
    }
    if gmail_scopes != {GMAIL_READONLY_SCOPE}:
        raise GmailConnectorError("gmail_scope_not_strictly_readonly")


ListMessages = Callable[..., Mapping[str, Any]]
GetMessage = Callable[..., Mapping[str, Any]]


class GmailReader:
    """Adapt Gmail list/get metadata calls to the existing read_page contract."""

    def __init__(
        self,
        *,
        query: str,
        list_messages: ListMessages,
        get_message: GetMessage,
        granted_scopes: Iterable[str],
    ) -> None:
        if not isinstance(query, str) or not query.strip():
            raise GmailConnectorError("gmail_query_required")
        if not callable(list_messages) or not callable(get_message):
            raise GmailConnectorError("gmail_read_operations_required")
        validate_gmail_scopes(granted_scopes)
        self._query = query
        self._list_messages = list_messages
        self._get_message = get_message
        self._message_refs: dict[str, str] = {}
        self._thread_refs: dict[str, str] = {}
        self._page_tokens: dict[str, str] = {}
        self._page_refs: dict[str, str] = {}

    def read_page(self, scope: Scope, cursor: str | None) -> Page:
        if not isinstance(scope, Scope) or scope.synthetic or scope.whole_mailbox:
            raise InventoryError("Invalid Gmail scope: expected a targeted real-data scope.")
        provider_page_token = None
        if cursor is not None:
            provider_page_token = self._page_tokens.get(cursor)
            if provider_page_token is None:
                raise InventoryError("Invalid Gmail continuation cursor.")

        try:
            response = self._list_messages(
                user_id="me",
                query=self._query,
                page_token=provider_page_token,
                fields=LIST_FIELDS,
            )
            summaries, next_page_token = self._parse_list(response)
            messages = tuple(self._read_message(summary) for summary in summaries)
        except InventoryError:
            raise
        except Exception:
            raise GmailConnectorError("gmail_reader_failure") from None

        next_cursor = None
        if next_page_token is not None:
            next_cursor = self._page_refs.get(next_page_token)
            if next_cursor is None:
                next_cursor = f"page-{len(self._page_tokens) + 1:06d}"
                self._page_refs[next_page_token] = next_cursor
                self._page_tokens[next_cursor] = next_page_token
        return Page(messages, next_cursor=next_cursor, complete=next_cursor is None)

    def _parse_list(
        self, response: Mapping[str, Any]
    ) -> tuple[tuple[tuple[str, str | None], ...], str | None]:
        if not isinstance(response, Mapping):
            raise InventoryError("Invalid Gmail list response.")
        raw_messages = response.get("messages", ())
        if not isinstance(raw_messages, list):
            raise InventoryError("Invalid Gmail message list.")
        parsed: list[tuple[str, str | None]] = []
        for summary in raw_messages:
            if not isinstance(summary, Mapping):
                raise InventoryError("Invalid Gmail message summary.")
            message_id = summary.get("id")
            thread_id = summary.get("threadId")
            if not isinstance(message_id, str) or not message_id:
                raise InventoryError("Invalid Gmail message identifier.")
            if thread_id is not None and (not isinstance(thread_id, str) or not thread_id):
                raise InventoryError("Invalid Gmail thread identifier.")
            parsed.append((message_id, thread_id))
        token = response.get("nextPageToken")
        if token is not None and (not isinstance(token, str) or not token):
            raise InventoryError("Invalid Gmail page token.")
        return tuple(parsed), token

    def _read_message(self, summary: tuple[str, str | None]) -> Message:
        message_id, summary_thread_id = summary
        response = self._get_message(
            user_id="me",
            message_id=message_id,
            format="metadata",
            fields=MESSAGE_FIELDS,
        )
        if not isinstance(response, Mapping):
            raise InventoryError("Invalid Gmail message response.")
        response_id = response.get("id")
        if response_id != message_id:
            raise InventoryError("Conflicting Gmail message identifier.")
        thread_id = response.get("threadId", summary_thread_id)
        if summary_thread_id is not None and thread_id != summary_thread_id:
            raise InventoryError("Conflicting Gmail thread identifier.")
        if thread_id is not None and (not isinstance(thread_id, str) or not thread_id):
            raise InventoryError("Invalid Gmail thread identifier.")

        size = _nonnegative_integer(response.get("sizeEstimate"), "message size")
        date = _internal_date(response.get("internalDate"))
        direction = _direction(response.get("labelIds"))
        attachments, completeness = _attachments(response.get("payload"))
        return Message(
            ref=self._opaque_ref(self._message_refs, message_id, "message"),
            thread_ref=(
                self._opaque_ref(self._thread_refs, thread_id, "thread")
                if thread_id is not None
                else None
            ),
            size_estimate_bytes=size,
            date=date,
            direction=direction,
            attachments=attachments,
            attachments_complete=completeness,
        )

    @staticmethod
    def _opaque_ref(mapping: dict[str, str], provider_id: str, prefix: str) -> str:
        if provider_id not in mapping:
            mapping[provider_id] = f"{prefix}-{len(mapping) + 1:06d}"
        return mapping[provider_id]


def _nonnegative_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    raise InventoryError(f"Invalid Gmail {field}.")


def _internal_date(value: Any) -> datetime | None:
    milliseconds = _nonnegative_integer(value, "internal date")
    if milliseconds is None:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise InventoryError("Invalid Gmail internal date.") from None


def _direction(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(label, str) for label in value):
        raise InventoryError("Invalid Gmail label evidence.")
    # SENT is explicit provider evidence. Received and self-sent require address
    # headers, which this privacy-limited connector intentionally does not read.
    return "sent" if "SENT" in value else None


def _attachments(payload: Any) -> tuple[tuple[Attachment, ...], bool | None]:
    if payload is None:
        return (), None
    if not isinstance(payload, Mapping):
        raise InventoryError("Invalid Gmail MIME metadata.")
    found: list[Attachment] = []

    def visit(part: Mapping[str, Any]) -> None:
        filename = part.get("filename")
        if filename is not None and not isinstance(filename, str):
            raise InventoryError("Invalid Gmail attachment filename.")
        if filename:
            body = part.get("body")
            if body is not None and not isinstance(body, Mapping):
                raise InventoryError("Invalid Gmail attachment metadata.")
            size = _nonnegative_integer(body.get("size") if body else None, "attachment size")
            found.append(Attachment(filename=filename, size_bytes=size))
        parts = part.get("parts", [])
        if not isinstance(parts, list):
            raise InventoryError("Invalid Gmail MIME parts.")
        for child in parts:
            if not isinstance(child, Mapping):
                raise InventoryError("Invalid Gmail MIME part.")
            visit(child)

    visit(payload)
    # Gmail's metadata format can expose MIME facts but does not promise a full
    # body tree. Keep enumeration conservative even when returned parts parse.
    return tuple(found), False


def build_google_reader(*, credentials: Any, query: str) -> GmailReader:
    """Hide the general Google service behind list/get-only callables."""
    validate_gmail_scopes(_credential_scopes(credentials))
    try:
        from googleapiclient.discovery import build

        messages = build(
            "gmail", "v1", credentials=credentials, cache_discovery=False
        ).users().messages()
    except Exception:
        raise GmailConnectorError("gmail_client_initialization_failed") from None

    def list_messages(**request: Any) -> Mapping[str, Any]:
        return messages.list(
            userId=request["user_id"],
            q=request["query"],
            pageToken=request["page_token"],
            fields=request["fields"],
        ).execute(num_retries=0)

    def get_message(**request: Any) -> Mapping[str, Any]:
        return messages.get(
            userId=request["user_id"],
            id=request["message_id"],
            format=request["format"],
            fields=request["fields"],
        ).execute(num_retries=0)

    return GmailReader(
        query=query,
        list_messages=list_messages,
        get_message=get_message,
        granted_scopes=_credential_scopes(credentials),
    )


def _credential_scopes(credentials: Any) -> Iterable[str] | None:
    granted = getattr(credentials, "granted_scopes", None)
    return granted if granted is not None else getattr(credentials, "scopes", None)
