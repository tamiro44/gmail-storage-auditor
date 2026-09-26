# Gmail Storage Auditor

A reusable, safety-first Gmail storage optimization skill/agent.

## Run a GitHub issue locally with Codex

The optional local issue runner turns one open GitHub issue into a reviewable implementation branch and pull request using the Codex CLI login already present on your machine:

```powershell
.\tools\run-issue.ps1 16
```

Run it from a normal VS Code PowerShell terminal. Prerequisites are Git, Python 3.11 or newer, [GitHub CLI](https://cli.github.com/), and [Codex CLI](https://learn.chatgpt.com/docs/non-interactive-mode). Authenticate GitHub with `gh auth login -h github.com` and Codex with `codex login` before the first run. The script requires the Codex status to report a ChatGPT login. It refuses to run when `OPENAI_API_KEY` or `CODEX_API_KEY` is present, never adds API billing or key configuration, and never reads, copies, exports, or writes Codex credentials. On Windows it prefers `codex.cmd`, avoiding execution-policy failures from an npm PowerShell shim.

The command must start with a completely clean Git working tree, including no untracked files. It fetches `origin/main`, updates local `main` only by fast-forward, and requires local and remote main to match. It refuses to overwrite an existing local or remote `agent/issue-<number>` branch. A failure leaves the current branch and any local changes available for manual inspection; rerun only after resolving them safely.

The runner fetches the issue with `gh`, creates `agent/issue-<number>`, and pipes the issue title/body plus the repository safety rules directly to `codex exec`. Codex runs ephemerally with `workspace-write`, rooted at this checkout, using the saved local ChatGPT/Codex authentication. The task forbids real Gmail access, credentials, mailbox content, Gmail API calls, and mailbox mutation; tests must use synthetic fixtures. It also tells Codex not to commit or publish anything.

After Codex returns, the script verifies that Git history did not change, runs the full unittest suite and `git diff --check`, requires an actual diff, and displays concise status/stat output. Only after all checks pass does the script commit, push the new branch, and open a pull request containing `Closes #<issue-number>`. It never merges. Human PR review and approval remain mandatory, especially for changes to Gmail permissions or mutation boundaries.

This local runner is independent of the existing `.github/workflows/codex-issue-orchestrator.yml`. That GitHub Actions workflow remains unchanged while the local approach is evaluated. The local script creates no task, transcript, credential, or agent-session file; `--ephemeral` disables durable Codex rollout files. Git commits, the pushed branch, and the pull request are the deliberate workflow outputs.

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

## Risk classification and protected-category policy (GSA-004)

`gmail_storage_auditor.risk.classify_risk` applies the checked-in defaults from
`config/policy.yaml` to normalized inventory records. Source-supplied category
hints retain their provenance, and every immutable result includes categories,
evidence, reasons, regret risk, and a conservative recommendation. Tax, legal,
financial, medical, identity, employment, and signed-document observations are
protected. Sentimental media defaults to Review.

Exact duplicate metadata remains visible in the classification, but it never
makes protected content Safe: the retained original stays Keep, and even a copy
with source-supported authority remains Review. Unknown context also defaults to
Review. An optional `SemanticClassifier` may add explainable findings; it cannot
establish duplicate identity, override deterministic protection, authorize an
action, or turn uncertainty into a Safe result. Failure or invalid semantic
output is represented as uncertainty without exposing provider errors.

The policy loader intentionally supports the repository's narrow scalar policy
surface and fails closed if required risk defaults are missing or weakened. This
stage performs no network access and has no mailbox action capability.

## Explicit quarantine review boundary (GSA-016)

`gmail_storage_auditor.quarantine` provides a separate, opt-in action API for applying the existing Gmail label named exactly `quarentine`. Read-only inventory and duplicate-analysis commands do not import or invoke this action path and remain mutation-free. The API accepts exact opaque references only through a `CandidateSelection` already produced by the project's candidate/safety policy, and requires a `QuarantineApproval` bound to the active interaction and an exact approved subset. Analysis output, a boolean, an old interaction, or an arbitrary Gmail query is not approval.

The narrow adapter first looks up the existing label and fails closed if it is absent; it never creates a label. For each approved message it calls only message-level label modification with `quarentine` in the add list and an empty remove list. It cannot trash, delete, archive, change read/unread state, mutate a thread, or remove existing labels. Each message is attempted at most once. Partial failures are reported with fixed reasons and opaque references only, without provider IDs or raw provider errors.

This optional action requires a distinct credential containing exactly one Gmail API scope: the minimum message-label mutation scope, `https://www.googleapis.com/auth/gmail.modify`. The only additional OAuth scopes permitted by the quarantine adapter are the OpenID Connect identity scopes `openid` and `email`, and only to bind an action to the authenticated account; no other non-Gmail scopes are accepted. The existing inventory credential remains strictly `gmail.readonly`; the read-only CLI does not request or accept the modify scope. The separately reviewed interactive workflow below uses the guarded adapter without silently upgrading existing tokens.

## Human-controlled Gmail quarantine command (GSA-017)

The normal `gmail_cli` command remains read-only. Quarantine is a separate,
interactive command with deliberately small hard limits: at most three Gmail
pages and ten displayed candidates. It first completes the bounded read-only
inventory and prints the full cleanup recommendation report. Quarantine is a
reversible human-review queue, not a deletion recommendation. Only Review
candidates with non-high risk, source-supported retained-copy evidence, known
estimated savings of at least 10 MiB, and a retained copy are offered. Protected,
sentimental, and all other high-risk items remain blocked, as do Keep,
unknown-size, unresolved-duplicate, and retained-copy messages. An incomplete scan or a run
with no eligible candidates stops without loading modify credentials. The page
limit is only a safety ceiling: it never makes a partial inventory actionable.
If the query reaches that ceiling, the command reports
`gmail_query_exceeded_bounded_scan_narrow_query` and requires a narrower query.

To reject obviously broad mutation scopes before authentication, the query must
contain a dedicated non-system `label:` and a second narrowing predicate such as
`larger:`, `after:`, or `rfc822msgid:`. Create and populate that dedicated label
manually with only the tiny set intended for this interaction; the command never
creates or expands labels or queries.

Prepare a second desktop OAuth client/token location outside the checkout. It
must be distinct from both read-only paths; the command requests only
`gmail.modify` for that token and never upgrades or reuses the read-only token.
After confirmation, it compares the two accounts through transient Gmail profile
lookups and fails closed if they differ or cannot be verified; account identifiers
are never printed or retained.
Create the Gmail label named exactly `quarentine` yourself before the run. The
command will not create it.

For an explicitly authorized, private smoke test, use a narrowly bounded query
and one candidate:

```powershell
python -B -m gmail_storage_auditor.gmail_quarantine_cli --query "label:gsa-quarantine-smoke larger:10M" --max-pages 1 --candidate-limit 1 --client-secrets "$env:LOCALAPPDATA\gmail-storage-auditor\readonly-client.json" --token "$env:LOCALAPPDATA\gmail-storage-auditor\readonly-token.json" --modify-client-secrets "$env:LOCALAPPDATA\gmail-storage-auditor\modify-client.json" --modify-token "$env:LOCALAPPDATA\gmail-storage-auditor\modify-token.json"
```

Human steps:

1. Confirm all four paths are outside this repository and pairwise distinct,
   and verify the existing modify token is scoped only to `gmail.modify`. Create
   `gsa-quarantine-smoke` manually and apply it only to the small controlled set
   you intend to audit.
2. Read the complete recommendation report before responding. If the scan is
   partial or no eligible recommendation is present, stop; do not broaden the
   query or policy merely to force a candidate.
3. At `Select candidate references`, type one displayed opaque
   `message-......` reference. Empty, duplicate, Keep, retained, or unknown
   references are rejected.
4. Re-check that exact message privately in Gmail. To proceed, type the exact
   phrase `APPLY QUARENTINE LABEL` at the next prompt. Any other input, Ctrl+C,
   or EOF cancels without requesting a Gmail mutation.
5. Review the opaque per-message result and then inspect the existing
   `quarentine` label in Gmail. This action only adds that label. It does not
   delete, Trash, archive, mark read/unread, remove labels, mutate a thread, or
   recover storage.

Do not paste real report output into repository files, logs, issues, or chat.
The smoke test above is a human-only procedure and is not run by tests or CI.

Quarantine is reversible human-review state, not deletion authorization. It does not delete, trash, archive, or recover storage. A future deletion workflow must require presence in `quarentine` as a necessary condition and must still obtain its own fresh, explicit authorization; this feature implements no deletion path. Automated tests use fabricated calls and request spies only. Any real-account smoke test must be explicitly user-initiated and limited to a controlled test message.

The final action boundary also requires the exact active policy selection, a
nonempty disjoint retained-copy set, the current interaction, interactive audit
mode, and a one-shot approval. Scheduled or recurring audits are always
report-only. See `docs/safety.md` for the threat and failure model.

## Standalone local HTML report

Append `--html <path>` to the existing Gmail CLI command to create a self-contained HTML inventory. Add `--duplicates` to include the existing duplicate-analysis results as well:

```powershell
python -B -m gmail_storage_auditor.gmail_cli --query "larger:10M" --max-pages 2 --client-secrets "$env:LOCALAPPDATA\gmail-storage-auditor\client.json" --token "$env:LOCALAPPDATA\gmail-storage-auditor\token.json" --duplicates --html "$env:LOCALAPPDATA\gmail-storage-auditor\report.html"
```

Open the resulting file directly in a browser. It includes summary metrics, coverage and limitations, the message inventory, duplicate evidence and retained-copy proposals when requested, and explicit analysis-only safety language. Without `--duplicates`, the duplicate section says analysis was not requested. Existing console output stays unchanged.

The file contains inline CSS, no JavaScript, no external resources, and a restrictive content security policy. All supplied text is HTML-escaped. Rendering makes no network calls and adds no server, browser launch, cache, or auxiliary files. The Gmail CLI still uses its existing read-only discovery and authentication flow; HTML export adds no Gmail operations or changes to analysis.

Append `--gmail-review-links` with `--html` to explicitly include **Open in
Gmail** links beside opaque run-local message references. They are omitted by
default. The connector forms a route only from an already returned, conservatively
validated hexadecimal message ID; invalid or unavailable IDs produce no link.
The raw provider ID is never visible link text. Review URLs remain separate from
`Inventory` and `DuplicateAnalysis`, are used only by the local HTML presentation,
and trigger no additional Gmail request. Opening one is a human browser action; it
does not authorize or perform a mailbox mutation.

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

## Explainable cleanup scoring and report (GSA-005)

`score_cleanup(duplicate_analysis, risk_classifications)` ranks each observed
message once using the versioned numeric inputs in `config/policy.yaml`.
Risk classifications are structurally bound to the exact immutable inventory,
duplicate analysis, and policy version that produced them; stale or substituted
same-reference results fail closed. Loaded and caller-supplied scoring policies
use the same validation rules.
Recommendations remain constrained by the earlier risk and retained-copy
decisions: proposed retained copies and messages without a source-supported
authoritative copy are Keep with zero estimated recovery. Under the current
conservative evidence model, eligible duplicate copies remain Review; empty
Safe and Aggressive groups are explicit rather than populated by weaker rules.
Those two recommendations are intentionally unreachable in v0.1 until a later
reviewed policy defines sufficient evidence; scoring cannot manufacture them.

`render_cleanup_report(plan)` produces a deterministic Markdown report with
Safe / Review / Aggressive / Keep sections, evidence, retained-copy details,
score components, and incremental/cumulative estimated savings. Whole-message
sizes are provider estimates, confidence percentages are configured heuristics,
and scores are derived ranking values—not measured recovered bytes or removal
probabilities. Synthetic reports explicitly label their fixture values as
illustrative. Neither API performs I/O or authorizes a mailbox action.

Unknown risk uses a larger divisor than known high risk because missing context
is treated as the most conservative ranking state. This affects ordering only:
both remain constrained to Review or Keep, and size or score cannot override the
retained-copy and protection gates.

## Advisory calibration and retrospective loop (GSA-007)

`evaluate_calibration(...)` compares versioned synthetic expectations with actual
recommendations and produces immutable observed signals, separate policy
judgments, limitations, and optional review-required proposals. It measures
recommendation drift, false Safe results, missed protection, retained-copy
violations, confidence drift, possible size dominance, and recurring synthetic
rejection patterns. `render_calibration_report(report)` returns a concise,
deterministic Markdown report without I/O.

The retro runs only at a meaningful synthetic milestone, a policy-version change,
or a fixture-suite change. It cannot modify policy or invoke mailbox actions.
Real feedback remains disabled in v0.1, and proposals must preserve or strengthen
safety and include rationale plus regression tests. See `docs/calibration.md`.

## Repository structure

- `SKILL.md` — reusable agent/skill workflow
- `AGENTS.md` — agent roles, coordination, and engineering rules
- `config/policy.yaml` — default safety and scoring policy
- `docs/architecture.md` — system design
- `gmail_storage_auditor/` — normalized read-only inventory, synthetic source, and text report
- `requirements-gmail.txt` — optional bounded dependencies for the read-only Gmail connector
- `tests/` — synthetic inventory and boundary tests
- `docs/safety.md` — enforced safety gates, approval contract, and failure model
- `docs/calibration.md` — retrospective triggers, signals, privacy, and review loop
- `docs/agent-board.md` — planned board/workflow documentation

## Status

GSA-002 implements normalized storage inventory; GSA-008 adds the read-only Gmail connector; GSA-003 adds optional deterministic duplicate metadata analysis and retained-copy proposals. The broader protection, scoring, recommendation, and approval workflow remains planned and tracked as GitHub Issues.
