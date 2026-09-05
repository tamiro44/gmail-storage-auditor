# Gmail Storage Auditor Skill

## Purpose

Audit a Gmail mailbox for storage recovery opportunities without making destructive changes during analysis.

## Workflow

1. **Inventory** — discover large, old, attachment-heavy, sent, forwarded, and self-sent messages.
2. **Cluster** — group likely duplicates using deterministic metadata first: filename, byte size, thread relationship, sender/recipient direction, and original-vs-forward evidence.
3. **Classify** — infer broad value/risk categories without exposing unnecessary message content.
4. **Protect** — default sensitive categories to Keep or Review unless a redundant copy is proven and an authoritative copy remains.
5. **Score** — estimate recoverable space, duplicate confidence, regret risk, and cleanup value.
6. **Recommend** — produce Safe / Review / Aggressive / Keep tiers with concise reasons.
7. **Approve** — request explicit user approval for exact messages/actions.
8. **Act** — only after approval, move selected messages to Trash using the connected mail tool.
9. **Report** — summarize estimated recovered space and retained safeguards.

## Required safety invariants

- Analysis is read-only.
- No deletion/trash action without explicit user approval in the current interaction.
- Never infer approval from a prior audit or scheduled run.
- Scheduled audits are report-only unless the user separately approves actions.
- Never commit or log real email bodies, personal identifiers, attachment contents, OAuth tokens, or mailbox exports.
- Tests use synthetic data only.
- Preserve at least one authoritative copy for every duplicate cluster selected for cleanup.

## Default protected categories

Tax, legal, financial, medical, identity, employment, signed documents, contracts, and other high-regret records.

## Duplicate confidence signals

Strong signals:
- exact filename + exact byte size
- original and forward in same thread
- sent/self-sent copy while another authoritative copy remains

Weak signals requiring review:
- similar filename only
- similar subject only
- near-size match
- semantically similar content without deterministic attachment evidence

## Report format

For each candidate show:
- estimated space saved
- confidence percentage
- risk tier
- recommendation
- short evidence/reason
- which retained copy protects against data loss

End with a Pareto-style summary: safe recovery first, incremental recovery from review/aggressive tiers, and a clear point where additional cleanup is no longer worth the risk.
