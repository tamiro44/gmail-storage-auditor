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

## Run a targeted read-only Gmail inventory (GSA-008)

The optional Gmail connector uses the same inventory pipeline. It requests exactly this OAuth scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

The connector rejects credentials that lack that scope or contain another Gmail scope. Its only Gmail operations are `users.messages.list` and `users.messages.get`; it has no mailbox-mutation method. It requests metadata fields for IDs, thread IDs, labels, internal dates, whole-message size estimates, and available MIME attachment filename/size facts. It does not request raw messages, bodies, snippets, address headers, or attachment data.

### Local setup

1. Create or select a Google Cloud project, enable the Gmail API, configure the OAuth consent screen, and add your Google account as a test user if the app remains in testing.
2. Create an OAuth client ID with application type **Desktop app**, then download its client JSON.
3. Create a directory outside this repository for the client JSON and token. For example, in PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\gmail-storage-auditor" | Out-Null
   Move-Item -LiteralPath "C:\path\to\downloaded-client.json" -Destination "$env:LOCALAPPDATA\gmail-storage-auditor\client.json"
   ```

4. Install the bounded Gmail dependencies in your preferred virtual environment:

   ```text
   python -m pip install -r requirements-gmail.txt
   ```

5. Run an explicit, bounded query. The token path may not exist on the first run, but its parent directory must exist:

   ```powershell
   python -B -m gmail_storage_auditor.gmail_cli --query "larger:10M" --max-pages 2 --client-secrets "$env:LOCALAPPDATA\gmail-storage-auditor\client.json" --token "$env:LOCALAPPDATA\gmail-storage-auditor\token.json"
   ```

   The first run opens Google's local installed-app authorization flow. Review the consent screen and approve only read-only Gmail access. The resulting token remains outside the repository. Later runs load or refresh that token and recheck its Gmail scopes.

The query is always required, and `--max-pages` must be positive. A finished run means only that the requested Gmail query finished; it never claims whole-mailbox coverage. Provider failures produce a partial report using successfully observed pages. Gmail IDs and page tokens are mapped to temporary run-local references before entering the inventory report.

Attachment enumeration remains marked incomplete because Gmail's metadata response does not guarantee a complete MIME body tree. Direction is shown as `sent` only when Gmail supplies the `SENT` label; received and self-sent status remain unknown because this connector does not request address headers. The output can contain real attachment filenames and dates and is intended for private local review. Do not paste it into issues, logs, tests, or repository files.

To revoke access, remove the app under your Google Account's third-party connections and delete the external token file. Never copy either credential file into this repository; common client/token JSON names are ignored, and the command refuses credential paths inside the checkout.

By default the connector command produces factual observed-storage inventory only. The optional GSA-003 analysis below consumes that same inventory; the connector's requests and normalization are unchanged.

## Duplicate metadata analysis (GSA-003)

Run the fabricated original/forward/sent/self-sent example without dependencies or network access:

```text
python -B -m gmail_storage_auditor.duplicate_demo
```

For private local Gmail analysis, append `--duplicates` to the existing bounded `gmail_cli` command. It appends a report after collecting the same inventory, without additional Gmail requests. No delete, trash, archive, label, read-state, or other mailbox mutation exists in this analysis. Real report output must stay outside repository artifacts and logs.

The Python entry points are `analyze_duplicates(inventory)` in `gmail_storage_auditor.duplicates` and `render_duplicates(analysis)` in `gmail_storage_auditor.duplicate_report`. Results are immutable records retaining the original inventory and its coverage status.

- Each cluster contains at least two distinct message references sharing an exact, case-sensitive filename and known exact attachment byte size. Zero bytes is valid; missing fields, near sizes, and similar names do not match. Repeated occurrences within one message count once. Overlapping attachment groups remain separate, avoiding transitive whole-message equivalence.
- `strong_metadata_match` is qualitative confidence in the metadata signal, following the existing policy. It is not a calibrated percentage or content-identity proof. No confidence mapping or policy defaults are changed.
- Exact `original` and `forwarded` hint values with source provenance support an original/forward relationship only within the same known thread and matched attachment group. Normalized `sent` and `self_sent` directions identify copy patterns but do not prove redundancy or authority. Unknown or unrelated hints do not establish relationships.
- One uncontradicted original with a same-thread forward is the proposed authoritative retained copy (`source_supported`). Multiple originals, contradictory hints, or absent supporting evidence leave authority `unresolved`; the smallest reference is a stable retention fallback for review, not an assertion of authorship. Dates and sent status alone never prove authority. Every cluster preserves a proposed retained member, and `retained_refs` contains their union across overlapping clusters.
- Gmail currently supplies no original/forward hints or self-sent direction, and marks attachment enumeration incomplete. Those facts remain unknown; this issue adds no headers, bodies, attachment downloads, scopes, or connector inference. Relationships are exercised with synthetic supplied observations.

Matched attachments do not establish whole-message redundancy: bodies, other attachments, and context may be unique. Reports show incomplete enumeration and partial scan limitations, propose no removal, and calculate no risk tiers, scores, or savings. Protection/scoring and approval work remain separate issues. An empty cluster list does not prove the observed messages are unique.

Run the full regression suite (inventory, connector, and duplicate analysis):

```text
python -B -m unittest discover -s tests -v
```

## Standalone local HTML report

Append `--html <path>` to the existing Gmail CLI command to create a self-contained HTML inventory. Add `--duplicates` to include the existing duplicate-analysis results as well:

```powershell
python -B -m gmail_storage_auditor.gmail_cli --query "larger:10M" --max-pages 2 --client-secrets "$env:LOCALAPPDATA\gmail-storage-auditor\client.json" --token "$env:LOCALAPPDATA\gmail-storage-auditor\token.json" --duplicates --html "$env:LOCALAPPDATA\gmail-storage-auditor\report.html"
```

Open the resulting file directly in a browser. It includes summary metrics, coverage and limitations, the message inventory, duplicate evidence and retained-copy proposals when requested, and explicit analysis-only safety language. Without `--duplicates`, the duplicate section says analysis was not requested. Existing console output stays unchanged.

The file contains inline CSS, no JavaScript, no external resources, and a restrictive content security policy. All supplied text is HTML-escaped. Rendering makes no network calls and adds no server, browser launch, cache, or auxiliary files. The Gmail CLI still uses its existing read-only discovery and authentication flow; HTML export adds no Gmail operations or changes to analysis.

The destination must be a new file in an existing directory outside the checkout, consistent with the repository privacy rule. Existing files are never overwritten. Errors use fixed diagnostics without exposing output paths. A disk/write failure may leave an incomplete file at the requested destination; no temporary report file is created. Real reports can contain private filenames and observations and must not be committed or shared in logs.

For already collected results, `gmail_storage_auditor.html_report.render_html(result)` accepts either an `Inventory` or a `DuplicateAnalysis` and returns an HTML string without I/O. The caller controls whether to save that string. Synthetic snapshots live in `tests/snapshots/`; the full regression command above checks them byte-for-byte after UTF-8 decoding.

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
- `requirements-gmail.txt` — optional bounded dependencies for the read-only Gmail connector
- `tests/` — synthetic inventory and boundary tests
- `docs/safety.md` — planned safety gates and approval model documentation
- `docs/agent-board.md` — planned board/workflow documentation

## Status

GSA-002 implements normalized storage inventory; GSA-008 adds the read-only Gmail connector; GSA-003 adds optional deterministic duplicate metadata analysis and retained-copy proposals. The broader protection, scoring, recommendation, and approval workflow remains planned and tracked as GitHub Issues.
