# Gmail Storage Auditor

A reusable, safety-first Gmail storage optimization skill/agent.

## Goal

Find storage-saving opportunities in Gmail while minimizing deletion regret. The system identifies large and old messages, duplicate attachments, forwarded/self-sent copies, low-value archives, and other cleanup candidates, then ranks them by expected space savings, confidence, and risk.

## Run the synthetic storage inventory (GSA-002)

Requires Python 3.11 or newer. From the repository root, run:

```text
python -B -m gmail_storage_auditor
```

No installation, third-party packages, credentials, network access, LLM, or agent harness are needed. The command reads only bundled, fabricated observations and writes a Markdown inventory to standard output. It does not connect to Gmail or import mailbox files.

The demo reports five unique messages, 19,922,944 bytes of known whole-message size estimates, and one message with unknown size. It lists the largest messages first, with UTC dates, age in whole elapsed days, direction, attachment-list completeness, and supplied hints with provenance. Its fixed audit time is September 7, 2026 at 00:00 UTC. Examples include large/old, sent, forwarded, self-sent, and incomplete observations.

These are observed storage facts, not a cleanup plan. Attachment bytes are not added to message totals. Unknown sizes remain unknown, and completing the demo's targeted scope does not imply complete mailbox coverage. The recommendation tiers and scoring described below belong to the full planned workflow; GSA-002 does not produce them or implement classification, content matching, retained-copy decisions, or any mailbox mutation capability.

Run the focused synthetic test suite:

```text
python -B -m unittest discover -s tests -v
```

The suite also runs the demo with Python socket creation, connection, and address lookup blocked, and checks that the inventory uses only the supplied read method.

## Read-only discovery boundary

`gmail_storage_auditor.inventory` defines immutable `Message`, `Attachment`, `Hint`, `Scope`, and `Page` records, plus `collect_inventory(reader, scope, as_of=..., max_pages=...)`. The collector requires only `reader.read_page(scope, cursor)`. The bundled `SyntheticReader` is the sole source implementation. There is no SDK, provider registry, policy loader, or action interface.

- References are run-local opaque strings. Dates are timezone-aware Python `datetime` values normalized to UTC; an unknown date is `None`. Dates later than the audit time are rejected.
- Message size estimates and exact attachment bytes are nonnegative integers or `None`. Attachment and hint collections are tuples. Attachment-list completeness is `True`, `False`, or `None` (unknown); an empty observed list does not prove that no attachments exist unless completeness is `True`.
- Direction is supplied as `received`, `sent`, `self_sent`, or `None`. Hints carry a value and source. The collector performs no text inference or risk classification.
- `Scope` declares its label, whether the whole mailbox was requested, and whether the source is synthetic. A page carries messages, an optional opaque next cursor, and explicit `complete`/`failed` flags. A completed or failed page cannot also advertise continuation.
- Identical observations sharing a reference count once. Conflicting records for that reference fail with `InventoryError`; matching metadata on different references never merges messages. Invalid data fails rather than returning a misleading summary. Diagnostics describe the problem without echoing payloads.
- A finite page limit, repeated cursor, reader failure, or missing completion signal returns a partial inventory of successfully observed records with a fixed reason. There are no retries or resume. Missing message fields are independent of scan completion.

The structured `Inventory` result contains ordered messages, scope, audit time, completion/reason, pages read, message count, known estimated bytes, and unknown-size count. Empty input has zero observed bytes; a nonempty inventory with no known sizes has an unknown total (`None`). Mixed known/unknown inputs total only known sizes. `render_inventory` presents these facts without calculating savings.

Only synthetic data is supported by the demo. This boundary does not certify a live connector's completeness, privacy, or behavior; live access is outside GSA-002.

## Core principles

- Analyze first; never delete during analysis.
- Require explicit user approval before moving any message to Trash.
- Protect sensitive categories by default: tax, legal, financial, medical, identity, employment, and signed documents.
- Treat sentimental media as review-only by default.
- Prefer deterministic duplicate evidence such as same filename + exact byte size + retained authoritative copy.
- Use synthetic fixtures for tests and examples. Never commit real mailbox content.

## Output tiers

- 🟢 Safe candidate — strong duplicate/redundancy evidence and low regret risk.
- 🟡 Review — likely removable, but context or value is uncertain.
- 🟠 Aggressive — meaningful space recovery with higher regret risk.
- 🔴 Keep — sensitive, authoritative, unique, or high-value content.

## Cleanup value

Conceptually:

`Cleanup Value = Space Saved × Confidence ÷ Risk`

The exact scoring model is configurable and should remain explainable.

## Repository structure

- `SKILL.md` — reusable agent/skill workflow
- `AGENTS.md` — agent roles, coordination, and engineering rules
- `config/policy.yaml` — default safety and scoring policy
- `docs/architecture.md` — system design
- `gmail_storage_auditor/` — normalized read-only inventory, synthetic source, and text report
- `tests/` — synthetic inventory and boundary tests
- `docs/safety.md` — planned safety gates and approval model documentation
- `docs/agent-board.md` — planned board/workflow documentation

## Status

GSA-002 implements a synthetic, report-only storage inventory. The broader audit workflow above remains planned; implementation tasks are tracked as GitHub Issues.
