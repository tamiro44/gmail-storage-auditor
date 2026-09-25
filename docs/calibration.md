# Calibration and retrospective loop

Calibration is an advisory, offline check of decision quality. It measures fixed
synthetic fixture outcomes and privacy-safe synthetic approval/rejection cohorts;
it cannot read Gmail, execute an action, edit policy, or approve its own proposal.

## When to run

Run a retrospective only when one of these explicit triggers occurs:

- after at least 10 comparable synthetic evaluations (`manual_milestone`);
- after a policy version changes (`policy_version_change`), even when the new
  fixture cohort is initially smaller; or
- after meaningful fixture-suite coverage changes (`fixture_suite_change`).

Do not run continuously or tune policy after every result. Small cohorts are
reported as insufficient evidence unless the purpose is reviewing a new policy
version.

## Accepted inputs

`SyntheticEvaluation` records contain fabricated fixture IDs, broad patterns,
expected and actual tiers, protection and retained-copy expectations, estimated
bytes, configured confidence, and derived score. `DecisionAggregate` accepts only
non-identifying synthetic counts by broad pattern and tier in v0.1. Real feedback
is rejected until consent, aggregation, and minimum-cohort rules receive separate
review. Message content, filenames, addresses, provider IDs, exact timestamps,
free text from users, and linkable per-audit records are not inputs.

## Measured signals

- recommendation mismatch count and rate;
- unexpected Safe recommendations;
- protected fixtures placed in Safe or Aggressive;
- unprotected fixtures kept contrary to expectations as a category-breadth signal;
- retained-copy violations, with zero tolerance;
- confidence differences beyond the configured tolerance;
- the largest fixture's share of total score as a size-dominance indicator; and
- adequately sized synthetic outcome cohorts above the rejection threshold.

The report keeps these observations separate from threshold-based policy
judgments. Approval/rejection is preference evidence, not proof that a message
was safe or that regret did not occur.

## Proposals and review

A `PolicyChangeProposal` must state a rationale, list regression tests, and
preserve or strengthen safety. It is rendered as `requires human review; not
applied`. Calibration has no write path to `config/policy.yaml` and no authority
to weaken protection, retention, approval, or action gates. Maintainers review a
proposal and its synthetic regression evidence through the normal issue and PR
workflow; accepted behavior requires a new policy version.
