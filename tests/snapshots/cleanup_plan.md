# Cleanup plan (synthetic fixture)

Policy version: 0.1
Analysis only: recommendations do not authorize mailbox changes or deletion.
Savings are whole-message provider estimates, not measured reclaimed storage. Scores are derived ranking values.
Synthetic fixture values are illustrative; they are not mailbox measurements.
Unknown values remain unknown. Retained and Keep items contribute zero estimated savings.

## Pareto summary

| Through tier | Incremental estimated savings | Cumulative estimated savings | Unknown-size candidates |
| --- | ---: | ---: | ---: |
| Safe | 0 bytes | 0 bytes | 0 |
| Review | 800 bytes | 800 bytes | 1 |
| Aggressive | 0 bytes | 800 bytes | 1 |
| Keep | 0 bytes | 800 bytes | 1 |

Safe recovery is shown first; Review and Aggressive add progressively less conservative options. Keep adds no recovery.

## Safe

No candidates.

## Review

### review-copy

- Estimated savings: 800 bytes
- Confidence: 85% heuristic (configured source-supported metadata heuristic)
- Risk tier: unknown
- Recommendation: review
- Cleanup score: 136
- Retained-copy information: retained
- Evidence: No protected category was recognized; missing context still requires review.; Duplicate metadata was recognized but does not prove whole-message redundancy.; A source-supported retained original exists; classification still remains conservative Review.; Source-supported retained-copy evidence makes this message eligible for conservative review.; exact_filename_and_byte_size; retained: original (source: synthetic fixture); same_thread_original_forward: retained, review-copy; same_thread_original_forward: retained, unknown-size-copy; review-copy: forwarded (source: synthetic fixture); review-copy: sent_copy_pattern (normalized direction); unknown-size-copy: forwarded (source: synthetic fixture); unknown-size-copy: sent_copy_pattern (normalized direction)
- Score components: estimated_savings_bytes=800 (Whole-message provider estimate; zero for Keep/retained items.); confidence_percent=85 (configured source-supported metadata heuristic); risk_weight=5 (Configured weight for unknown risk.); formula=savings * confidence / (100 * risk_weight) (Integer ranking value; not measured bytes or a probability of safe removal.)

### unknown-size-copy

- Estimated savings: unknown
- Confidence: 85% heuristic (configured source-supported metadata heuristic)
- Risk tier: unknown
- Recommendation: review
- Cleanup score: unknown
- Retained-copy information: retained
- Evidence: No protected category was recognized; missing context still requires review.; Duplicate metadata was recognized but does not prove whole-message redundancy.; A source-supported retained original exists; classification still remains conservative Review.; Source-supported retained-copy evidence makes this message eligible for conservative review.; exact_filename_and_byte_size; retained: original (source: synthetic fixture); same_thread_original_forward: retained, review-copy; same_thread_original_forward: retained, unknown-size-copy; review-copy: forwarded (source: synthetic fixture); review-copy: sent_copy_pattern (normalized direction); unknown-size-copy: forwarded (source: synthetic fixture); unknown-size-copy: sent_copy_pattern (normalized direction)
- Score components: estimated_savings_bytes=unknown (Whole-message provider estimate; zero for Keep/retained items.); confidence_percent=85 (configured source-supported metadata heuristic); risk_weight=5 (Configured weight for unknown risk.); formula=savings * confidence / (100 * risk_weight) (Integer ranking value; not measured bytes or a probability of safe removal.)

## Aggressive

No candidates.

## Keep

### retained

- Estimated savings: 0 bytes
- Confidence: unknown (unknown; no duplicate cleanup evidence)
- Risk tier: unknown
- Recommendation: keep
- Cleanup score: unknown
- Retained-copy information: retained
- Evidence: No protected category was recognized; missing context still requires review.; Duplicate metadata was recognized but does not prove whole-message redundancy.; Proposed retained copy contributes zero recoverable bytes.; exact_filename_and_byte_size; retained: original (source: synthetic fixture); same_thread_original_forward: retained, review-copy; same_thread_original_forward: retained, unknown-size-copy; review-copy: forwarded (source: synthetic fixture); review-copy: sent_copy_pattern (normalized direction); unknown-size-copy: forwarded (source: synthetic fixture); unknown-size-copy: sent_copy_pattern (normalized direction)
- Score components: estimated_savings_bytes=0 (Whole-message provider estimate; zero for Keep/retained items.); confidence_percent=unknown (unknown; no duplicate cleanup evidence); risk_weight=5 (Configured weight for unknown risk.); formula=savings * confidence / (100 * risk_weight) (Integer ranking value; not measured bytes or a probability of safe removal.)

### unique-protected

- Estimated savings: 0 bytes
- Confidence: unknown (unknown; no duplicate cleanup evidence)
- Risk tier: high
- Recommendation: keep
- Cleanup score: unknown
- Retained-copy information: none
- Evidence: Protected category requires conservative retention.; No source-supported authoritative retained copy permits a cleanup estimate.
- Score components: estimated_savings_bytes=0 (Whole-message provider estimate; zero for Keep/retained items.); confidence_percent=unknown (unknown; no duplicate cleanup evidence); risk_weight=4 (Configured weight for high risk.); formula=savings * confidence / (100 * risk_weight) (Integer ranking value; not measured bytes or a probability of safe removal.)
