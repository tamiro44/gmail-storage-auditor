# Safety and approval boundary

Gmail Storage Auditor separates analysis from mailbox mutation. Inventory,
duplicate detection, risk classification, scoring, and reports have no action
port and cannot authorize an action. Their output is evidence for review only.

## v0.1 action scope

The only mailbox-changing adapter adds the existing Gmail label named exactly
`quarentine` to exact message references. It cannot create labels, remove labels,
archive, change read state, mutate threads, move messages to Trash, or delete
messages. Permanent deletion is outside v0.1.

Quarantine is reversible review state. It does not recover storage and does not
authorize a later Trash or deletion operation. Any future destructive workflow
requires separate design, review, credentials, and fresh explicit approval.

## Authorization contract

An action requires all of the following immutable records and runtime state:

- A `CandidateSelection` containing exact opaque candidate references, at least
  one distinct retained-copy reference, the active policy version, and a
  selection revision. Candidate and retained references cannot overlap.
- A `QuarantineApproval` for the exact `apply_quarentine_label` action and an
  exact nonempty subset of that selection.
- The same active selection and interaction reference at the final adapter
  boundary. A changed selection, policy version, retained set, or revision makes
  an earlier approval invalid.
- Interactive audit mode. Scheduled and recurring audits are report-only and
  cannot consume approval or invoke provider operations.
- A one-shot approval. After an attempt starts, success, failure, or an unknown
  provider outcome all require a new interaction and approval before another
  attempt.

A report, recommendation, query, boolean, model statement, prior interaction,
or scheduled job is never approval. All selected opaque references must resolve
through the adapter's private mapping before the first mutation.

## Threat and failure model

| Threat or failure | Required behavior |
| --- | --- |
| Missing, malformed, wrong-action, or prior-interaction approval | Deny before provider calls. |
| Selection, policy, revision, or retained-copy set changed after approval | Deny; recompute and request fresh approval. |
| Empty retained-copy set or a candidate also selected as retained | Deny construction of the selection. |
| Scheduled or recurring audit attempts an action | Deny before provider calls; produce reports only. |
| Missing or ambiguous `quarentine` label | Deny without creating a label or modifying a message. |
| Approved reference cannot be privately resolved | Deny the whole selection before the first mutation. |
| Provider failure or uncertain response | Report a fixed per-reference failure, do not expose provider details, and do not retry automatically. |
| Approval replay | Deny after the first attempted execution. |
| Credential has broader or different Gmail scopes | Deny adapter construction. |
| Analysis output is passed directly as an action request | Deny because it is not current approval bound to the active selection. |

Message-level Gmail modifications are not transactional. The adapter serializes
attempts, tries each approved message at most once, and reports partial success
honestly. It never converts a read or provider failure into permission for a
different operation.

## Privacy and testing

Provider message IDs remain inside the adapter mapping. Public selections,
approvals, results, and errors use run-local opaque references and fixed failure
codes. Raw provider errors, mailbox content, credentials, and personal data must
not enter reports, tests, logs, or repository artifacts.

Safety tests use fabricated references, request spies, and synthetic provider
failures. They verify that denied paths make no mutation calls and that the only
allowed request is message-level addition of the existing `quarentine` label.
