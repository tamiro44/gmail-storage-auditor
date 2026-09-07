"""Normalized observations and bounded, read-only inventory collection."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class InventoryError(ValueError):
    """Invalid inventory input. Messages describe fields, never their values."""


def _text(value: object, field: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"Invalid {field}: expected nonempty text.")


def _size(value: object) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise InventoryError("Invalid size: expected nonnegative integer bytes or unknown.")


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InventoryError("Invalid date: expected a timezone-aware datetime.")
    try:
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise InventoryError("Invalid date: cannot normalize to UTC.") from None


def _records(value: object, record_type: type) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, record_type) for item in value):
        raise InventoryError("Invalid record collection: expected a tuple of normalized records.")


@dataclass(frozen=True)
class Attachment:
    filename: str | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        _text(self.filename, "attachment filename", optional=True)
        _size(self.size_bytes)


@dataclass(frozen=True)
class Hint:
    """A source-supplied observation; no classification is performed here."""

    value: str
    source: str

    def __post_init__(self) -> None:
        _text(self.value, "hint")
        _text(self.source, "hint provenance")


@dataclass(frozen=True)
class Message:
    ref: str
    size_estimate_bytes: int | None = None
    date: datetime | None = None
    thread_ref: str | None = None
    direction: str | None = None
    attachments: tuple[Attachment, ...] = ()
    attachments_complete: bool | None = None
    hints: tuple[Hint, ...] = ()

    def __post_init__(self) -> None:
        _text(self.ref, "message reference")
        _size(self.size_estimate_bytes)
        if self.date is not None:
            object.__setattr__(self, "date", _utc(self.date))
        _text(self.thread_ref, "thread reference", optional=True)
        if self.direction not in (None, "received", "sent", "self_sent"):
            raise InventoryError("Invalid direction: expected received, sent, self_sent, or unknown.")
        _records(self.attachments, Attachment)
        if self.attachments_complete is not None and type(self.attachments_complete) is not bool:
            raise InventoryError("Invalid attachment completeness: expected boolean or unknown.")
        _records(self.hints, Hint)


@dataclass(frozen=True)
class Scope:
    """Declared source coverage; a completed targeted scan is still targeted."""

    label: str
    whole_mailbox: bool = False
    synthetic: bool = False

    def __post_init__(self) -> None:
        _text(self.label, "scope")
        if type(self.whole_mailbox) is not bool or type(self.synthetic) is not bool:
            raise InventoryError("Invalid scope flags: expected booleans.")


@dataclass(frozen=True)
class Page:
    """One page; failed may accompany valid observations but never completion."""

    messages: tuple[Message, ...]
    next_cursor: str | None = None
    complete: bool = False
    failed: bool = False

    def __post_init__(self) -> None:
        _records(self.messages, Message)
        _text(self.next_cursor, "continuation cursor", optional=True)
        if type(self.complete) is not bool or type(self.failed) is not bool:
            raise InventoryError("Invalid page flags: expected booleans.")
        if (self.complete and self.failed) or (
            self.next_cursor is not None and (self.complete or self.failed)
        ):
            raise InventoryError("Invalid page: contradictory continuation/completion status.")


class Reader(Protocol):
    def read_page(self, scope: Scope, cursor: str | None) -> Page:
        """Read one page for the declared scope. No other capability is required."""
        ...


@dataclass(frozen=True)
class Inventory:
    scope: Scope
    as_of: datetime
    messages: tuple[Message, ...]
    complete: bool
    partial_reason: str | None
    pages_read: int

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def unknown_size_count(self) -> int:
        return sum(message.size_estimate_bytes is None for message in self.messages)

    @property
    def known_estimated_bytes(self) -> int | None:
        if self.messages and self.unknown_size_count == self.message_count:
            return None
        return sum(
            message.size_estimate_bytes
            for message in self.messages
            if message.size_estimate_bytes is not None
        )


def collect_inventory(
    reader: Reader, scope: Scope, *, as_of: datetime, max_pages: int
) -> Inventory:
    """Collect one bounded scope. Invalid data fails; read interruptions return partial facts."""
    if not isinstance(scope, Scope):
        raise InventoryError("Invalid scope: expected a normalized Scope.")
    as_of = _utc(as_of)
    if type(max_pages) is not int or max_pages < 1:
        raise InventoryError("Invalid scan bound: expected a positive integer page limit.")

    observed: dict[str, Message] = {}
    requested_cursors: set[str | None] = set()
    cursor = None
    pages_read = 0
    complete = False
    reason = "page_limit"
    for _ in range(max_pages):
        requested_cursors.add(cursor)
        try:
            page = reader.read_page(scope, cursor)
        except InventoryError:
            # A reader may discover malformed input while constructing records.
            # Do not trust exception text supplied by a reader.
            raise InventoryError("Invalid observation returned by reader.") from None
        except Exception:
            reason = "reader_failure"
            break
        if not isinstance(page, Page):
            raise InventoryError("Invalid discovery page: expected a normalized Page.")
        pages_read += 1
        for message in page.messages:
            if message.date is not None and message.date > as_of:
                raise InventoryError("Invalid message date: later than the audit time.")
            previous = observed.get(message.ref)
            if previous is not None and previous != message:
                raise InventoryError("Conflicting observations for a message reference.")
            observed[message.ref] = message

        if page.failed:
            reason = "reader_failure"
            break
        if page.complete:
            complete, reason = True, None
            break
        if page.next_cursor is None:
            reason = "source_incomplete"
            break
        if page.next_cursor in requested_cursors:
            reason = "repeated_cursor"
            break
        cursor = page.next_cursor

    messages = tuple(sorted(
        observed.values(),
        key=lambda message: (
            message.size_estimate_bytes is None,
            -(message.size_estimate_bytes or 0),
            message.ref,
        ),
    ))
    return Inventory(scope, as_of, messages, complete, reason, pages_read)
