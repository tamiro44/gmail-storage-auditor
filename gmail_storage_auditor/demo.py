"""Bundled synthetic observations. All references, filenames and hints are fabricated."""

from datetime import datetime, timezone

from .inventory import Attachment, Hint, InventoryError, Message, Page, Scope, collect_inventory
from .report import render_inventory


AS_OF = datetime(2026, 9, 7, tzinfo=timezone.utc)
SCOPE = Scope("bundled attachment and direction examples", synthetic=True)
_MIB = 1024 * 1024
_LARGE = Message(
    "synthetic-large", 12 * _MIB, datetime(2020, 1, 1, tzinfo=timezone.utc),
    thread_ref="synthetic-thread-a", direction="received",
    attachments=(Attachment("sample-video.bin", 8 * _MIB), Attachment("sample-notes.txt", 1024)),
    attachments_complete=True,
)
_SENT = Message(
    "synthetic-sent", 4 * _MIB, datetime(2025, 1, 1, tzinfo=timezone.utc),
    direction="sent", attachments=(Attachment("sample-slide.bin", 3 * _MIB),),
    attachments_complete=True,
)
_FORWARDED = Message(
    "synthetic-forwarded", 2 * _MIB, datetime(2026, 1, 1, tzinfo=timezone.utc),
    thread_ref="synthetic-thread-b", direction="received",
    attachments=(Attachment("sample-forward.bin", None),), attachments_complete=False,
    hints=(Hint("forwarded", "synthetic fixture"),),
)
_SELF_SENT = Message(
    "synthetic-self-sent", _MIB, datetime(2026, 9, 1, tzinfo=timezone.utc),
    direction="self_sent", attachments_complete=True,
    hints=(Hint("self-sent", "synthetic fixture"),),
)
_UNKNOWN = Message("synthetic-unknown")


class SyntheticReader:
    """Exactly one bundled scope and two pages, including a repeated observation."""

    def read_page(self, scope: Scope, cursor: str | None) -> Page:
        if scope != SCOPE:
            raise InventoryError("Unsupported synthetic scope.")
        if cursor is None:
            return Page((_LARGE, _SENT), next_cursor="second-page")
        if cursor == "second-page":
            return Page((_LARGE, _FORWARDED, _SELF_SENT, _UNKNOWN), complete=True)
        raise InventoryError("Invalid synthetic cursor.")


def main() -> None:
    inventory = collect_inventory(SyntheticReader(), SCOPE, as_of=AS_OF, max_pages=2)
    print(render_inventory(inventory), end="")
