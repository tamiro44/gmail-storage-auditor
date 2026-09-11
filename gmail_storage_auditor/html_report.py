"""Standalone HTML presentation. Pure rendering: no analysis, I/O, or network."""

from html import escape

from .duplicates import DuplicateAnalysis
from .inventory import Inventory


def _text(value: object) -> str:
    return escape("unknown" if value is None else str(value), quote=True)


def _list(values) -> str:
    return "<ul>" + "".join(f"<li>{_text(value)}</li>" for value in values) + "</ul>"


def _facts(items) -> str:
    return "<dl>" + "".join(
        f"<dt>{_text(label)}</dt><dd>{_text(value)}</dd>" for label, value in items
    ) + "</dl>"


def render_html(result: Inventory | DuplicateAnalysis) -> str:
    """Render supplied results in their existing order, without recomputing analysis."""
    analysis = result if isinstance(result, DuplicateAnalysis) else None
    inventory = analysis.inventory if analysis is not None else result
    lines = [
        "<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        "<title>Gmail Storage Auditor report</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;line-height:1.5;color:#172b3a;background:#f4f6f8;margin:0}",
        "main{max-width:1200px;margin:auto;padding:2rem}h1,h2,h3{line-height:1.2}",
        "section,article{background:white;border:1px solid #cbd5df;border-radius:.5rem;padding:1rem;margin:1rem 0}",
        ".notice{border-left:5px solid #956000}dl{display:grid;grid-template-columns:minmax(10rem,1fr) 2fr;gap:.4rem 1rem}",
        "dt{font-weight:bold}dd{margin:0}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}",
        "th,td{text-align:left;vertical-align:top;border-bottom:1px solid #cbd5df;padding:.6rem;overflow-wrap:anywhere}",
        "th{background:#edf2f7}li,dd,p{overflow-wrap:anywhere}td ul{margin:0;padding-left:1rem}",
        "@media print{body{background:white}main{padding:0;max-width:none}.table-scroll{overflow:visible}section,article{break-inside:avoid}}",
        "</style>", "</head>", "<body>", "<main>", "<h1>Gmail Storage Auditor</h1>",
        '<section class="notice" aria-label="Analysis-only safety notice">',
        "<h2>Analysis only</h2>",
        "<p>This report does not delete, trash, archive, change labels or read state, or make any other Gmail mutation. It grants no approval for mailbox changes.</p>",
        "<p>No removal recommendations, risk tiers, scores, or savings estimates are produced. Retained copies are proposals for review, not proof that a whole message is redundant.</p>",
        "<p>Private local report: filenames, dates, and supplied observations may be sensitive. Keep this file out of repositories and shared logs.</p>", "</section>",
        "<section><h2>Summary</h2>",
        _facts((
            ("Source", "synthetic" if inventory.scope.synthetic else "non-synthetic"),
            ("Scope", inventory.scope.label),
            ("Coverage", "whole mailbox requested" if inventory.scope.whole_mailbox else "targeted scope only"),
            ("As of (UTC)", inventory.as_of.isoformat()),
            ("Scan", "complete for requested scope" if inventory.complete else "partial"),
            ("Pages read", inventory.pages_read),
            ("Unique observed messages", inventory.message_count),
            ("Known whole-message estimated bytes", inventory.known_estimated_bytes),
            ("Messages with unknown size", inventory.unknown_size_count),
            ("Duplicate metadata clusters", len(analysis.clusters) if analysis is not None else "not analyzed"),
        )), "</section>", '<section class="notice"><h2>Limitations and warnings</h2>',
    ]
    warnings = [
        "Storage estimates apply only to observed records; they do not measure account quota or recoverable space.",
        "Attachment bytes are not added to whole-message totals. Unknown sizes remain unknown.",
        "Completion of a targeted scope does not imply whole-mailbox coverage.",
        "Metadata equality does not prove identical attachment content or whole-message redundancy.",
    ]
    if not inventory.complete:
        reasons = {"reader_failure": "reader failed", "page_limit": "page limit reached",
                   "repeated_cursor": "source repeated a continuation cursor",
                   "source_incomplete": "source did not confirm completion"}
        warnings.append("Partial inventory: " + reasons.get(inventory.partial_reason, "incomplete scan") + "; only successfully observed records are included.")
    if any(message.attachments_complete is not True for message in inventory.messages):
        warnings.append("Attachment enumeration is incomplete or unknown for one or more messages.")
    lines.extend([_list(warnings), "</section>", "<section><h2>Message inventory</h2>",
                  '<div class="table-scroll"><table>', "<caption>Observed messages in inventory order</caption>",
                  "<thead><tr>" + "".join(f'<th scope="col">{label}</th>' for label in
                  ("Reference", "Estimated bytes", "Date (UTC)", "Age (days)", "Thread", "Direction", "Attachments", "Supplied observations")) + "</tr></thead>", "<tbody>"])
    for message in inventory.messages:
        cells = [_text(message.ref), _text(message.size_estimate_bytes),
                 _text(message.date.isoformat() if message.date else None),
                 _text((inventory.as_of - message.date).days if message.date else None),
                 _text(message.thread_ref), _text(message.direction)]
        completeness = "complete" if message.attachments_complete is True else "partial" if message.attachments_complete is False else "unknown"
        cells.append(f"<p>{len(message.attachments)} observed; list {completeness}</p>" + _list(
            f"{a.filename if a.filename is not None else 'unknown'} ({a.size_bytes if a.size_bytes is not None else 'unknown'} bytes)" for a in message.attachments))
        cells.append(_list(f"{hint.value} (source: {hint.source})" for hint in message.hints) if message.hints else "unknown")
        lines.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    lines.extend(["</tbody></table></div>"])
    if not inventory.messages:
        lines.append("<p>No messages observed.</p>")
    lines.extend(["</section>", "<section><h2>Duplicate clusters</h2>"])
    if analysis is None:
        lines.append("<p>Duplicate analysis was not requested.</p>")
    else:
        lines.append("<p>Confidence describes qualitative metadata evidence, not a calibrated probability of identical content.</p>")
        lines.append("<h3>All proposed retained references across overlapping clusters</h3>")
        lines.append(_list(analysis.retained_refs) if analysis.retained_refs else "<p>None.</p>")
        if not analysis.clusters:
            lines.append("<p>No exact attachment metadata matches across observed messages; this does not prove uniqueness.</p>")
        for cluster in analysis.clusters:
            lines.extend(["<article>", f"<h3>{_text(cluster.filename)}</h3>", _facts((
                ("Exact attachment bytes", cluster.size_bytes), ("Confidence", cluster.confidence),
                ("Proposed retained copy", cluster.retained_ref), ("Authority", cluster.authority),
                ("Retention reason", cluster.retention_reason))),
                "<h4>Members</h4>", _list(cluster.members), "<h4>Evidence</h4>", _list(cluster.evidence),
                "<h4>Limitations</h4>", _list(cluster.limitations), "</article>"])
    lines.extend(["</section>", "</main>", "</body>", "</html>"])
    return "\n".join(lines) + "\n"
