"""Plain inventory presentation. Sizes describe observations only."""

from html import escape

from .inventory import Inventory


def _cell(value: object) -> str:
    if value is None:
        return "unknown"
    text = "".join(character if character.isprintable() else " " for character in str(value))
    return escape(" ".join(text.split())).replace("|", "&#124;")


def render_inventory(inventory: Inventory) -> str:
    coverage = "whole mailbox requested" if inventory.scope.whole_mailbox else "targeted scope only"
    status = "complete for requested scope" if inventory.complete else "partial"
    known_bytes = inventory.known_estimated_bytes
    size_text = "unknown (no known message sizes)" if known_bytes is None else f"{known_bytes:,} bytes"
    lines = [
        "# Storage inventory" + (" (synthetic demo)" if inventory.scope.synthetic else ""),
        "",
        f"Scope: {_cell(inventory.scope.label)} ({coverage})",
        f"As of: {inventory.as_of.isoformat()}",
        f"Scan: {status}; pages read: {inventory.pages_read}",
    ]
    if not inventory.complete:
        reasons = {
            "reader_failure": "reader failed; only successfully observed records are included",
            "page_limit": "page limit reached",
            "repeated_cursor": "source repeated a continuation cursor",
            "source_incomplete": "source did not confirm completion",
        }
        lines.append("Partial reason: " + reasons.get(inventory.partial_reason, "incomplete scan"))
    lines.extend([
        f"Unique observed messages: {inventory.message_count}",
        f"Known whole-message size estimates (observed records only): {size_text}",
        f"Messages with unknown size: {inventory.unknown_size_count}",
        "",
        "These are observed storage estimates; they do not measure account quota or recoverable space.",
        "Attachment bytes are shown separately and are not added to the message total.",
        "",
        "| Reference | Estimated bytes | Date (UTC) | Age (days) | Thread | Direction | Attachments | Supplied observations |",
        "| --- | ---: | --- | ---: | --- | --- | --- | --- |",
    ])
    for message in inventory.messages:
        age = (inventory.as_of - message.date).days if message.date is not None else None
        completeness = (
            "complete" if message.attachments_complete is True
            else "partial" if message.attachments_complete is False else "unknown"
        )
        attachments = "; ".join(
            f"{_cell(item.filename)} ({_cell(item.size_bytes)} bytes)"
            for item in message.attachments
        )
        attachment_text = (
            f"{len(message.attachments)} observed; list {completeness}"
            + (f"; {attachments}" if attachments else "")
        )
        hints = "; ".join(
            f"{_cell(hint.value)} (source: {_cell(hint.source)})" for hint in message.hints
        ) or "unknown"
        cells = [
            _cell(message.ref), _cell(message.size_estimate_bytes),
            _cell(message.date.isoformat() if message.date else None), _cell(age),
            _cell(message.thread_ref), _cell(message.direction), attachment_text, hints,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
