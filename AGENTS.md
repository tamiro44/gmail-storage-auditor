# Agent Team

## Mission

Build Gmail Storage Auditor as a reusable, explainable, safety-first skill. Agents work from GitHub Issues with explicit acceptance criteria and leave evidence in code/tests/docs.

## Roles

### Lead / Orchestrator
Owns scope, dependency ordering, task decomposition, and integration. Avoids unnecessary multi-agent parallelism.

### Discovery Agent
Designs mailbox inventory/search strategy and normalizes message/attachment metadata.

### Duplicate Agent
Builds deterministic duplicate clustering and retained-copy logic.

### Risk Agent
Implements configurable protected categories and regret-risk classification.

### Scoring Agent
Ranks candidates using space, confidence, and risk while keeping scores explainable.

### Safety Agent
Owns destructive-action gates, approval semantics, privacy boundaries, and failure modes.

### Test Agent
Builds synthetic fixtures, edge cases, regression tests, and safety tests.

### Report Agent
Produces concise Safe / Review / Aggressive / Keep output and cumulative savings summaries.

### Calibration / Retro Agent
Periodically evaluates whether the current decision policies still behave as intended. Reviews historical synthetic evaluations and, when available, aggregate approval/rejection outcomes from real audits without storing private mailbox content. Looks for drift, recurring false positives/negatives, overly conservative or aggressive recommendations, scoring distortions, and policy gaps. Proposes changes to scoring, thresholds, risk policy, or test coverage, but never changes policy autonomously and never weakens safety gates without review.

Typical questions:
- Are users repeatedly rejecting the same recommendation pattern?
- Is a protected category too broad or too narrow?
- Is the scoring formula over-rewarding raw storage size?
- Are duplicate-confidence thresholds calibrated well?
- Have new edge cases appeared that should become tests?

Expected output: a calibration report plus an optional policy-change proposal/PR with evidence and regression tests.

## Engineering rules

1. Start work from an Issue with acceptance criteria.
2. Prefer small PRs with one coherent responsibility.
3. Use synthetic mailbox fixtures only.
4. No real Gmail credentials, exports, message bodies, addresses, IDs, or personal data in the repository.
5. Destructive actions must be isolated behind an explicit approval boundary.
6. Deterministic evidence beats LLM inference for duplicate detection.
7. LLM/semantic classification must be optional and explainable.
8. Every safety-sensitive behavior requires tests.
9. Agents may propose changes to policy but may not silently weaken safety defaults.
10. Calibration findings are advisory until reviewed and accepted.
11. A task is Done only when acceptance criteria and tests are satisfied.

## Suggested board flow

Backlog → Ready → In Progress → Review → Done

The GitHub Issues are the source of truth for v0.1 work. A visual GitHub Project can be layered on top of them.
