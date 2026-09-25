"""Explainable cleanup ranking over duplicate and risk evidence; no actions."""

from dataclasses import dataclass

from .duplicates import DuplicateAnalysis
from .policy import ScoringPolicy, load_scoring_policy
from .risk import RiskClassification


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    value: str
    explanation: str


@dataclass(frozen=True)
class CleanupCandidate:
    message_ref: str
    estimated_savings_bytes: int | None
    confidence_percent: int | None
    confidence_basis: str
    risk_tier: str
    recommendation: str
    score: int | None
    evidence: tuple[str, ...]
    retained_copy_refs: tuple[str, ...]
    components: tuple[ScoreComponent, ...]


@dataclass(frozen=True)
class CleanupPlan:
    duplicates: DuplicateAnalysis
    policy_version: str
    candidates: tuple[CleanupCandidate, ...]


def score_cleanup(
    duplicates: DuplicateAnalysis,
    classifications: tuple[RiskClassification, ...],
    *,
    policy: ScoringPolicy | None = None,
) -> CleanupPlan:
    """Rank each observed message once without relaxing classification policy."""
    policy = policy or load_scoring_policy()
    if not isinstance(duplicates, DuplicateAnalysis):
        raise ValueError("Duplicate analysis is required for cleanup scoring.")
    if not isinstance(classifications, tuple) or any(
        not isinstance(item, RiskClassification) for item in classifications
    ):
        raise ValueError("Risk classifications must be normalized records.")
    by_ref = {item.message_ref: item for item in classifications}
    expected = {message.ref for message in duplicates.inventory.messages}
    if set(by_ref) != expected or len(by_ref) != len(classifications):
        raise ValueError("Risk classifications must cover the duplicate inventory exactly once.")
    clusters_by_ref = {
        ref: tuple(cluster for cluster in duplicates.clusters if ref in cluster.members)
        for ref in expected
    }
    candidates = []
    for message in duplicates.inventory.messages:
        risk = by_ref[message.ref]
        if (risk.source_inventory != duplicates.inventory
                or risk.source_duplicates != duplicates
                or risk.policy_version != policy.version):
            raise ValueError(
                "Risk classifications must belong to the exact inventory, "
                "duplicate analysis, and policy version being scored."
            )
        if risk.risk not in ("high", "unknown") or risk.recommendation not in ("review", "keep"):
            raise ValueError("Risk classification contains an unsupported safety decision.")
        clusters = clusters_by_ref[message.ref]
        retained = tuple(sorted({cluster.retained_ref for cluster in clusters}))
        removable_clusters = tuple(c for c in clusters if c.retained_ref != message.ref)
        supported = tuple(c for c in removable_clusters if c.authority == "source_supported")

        if message.ref in duplicates.retained_refs:
            recommendation = "keep"
            decision = "Proposed retained copy contributes zero recoverable bytes."
        elif not supported:
            recommendation = "keep"
            decision = "No source-supported authoritative retained copy permits a cleanup estimate."
        else:
            recommendation = risk.recommendation
            decision = "Source-supported retained-copy evidence makes this message eligible for conservative review."
        savings = message.size_estimate_bytes if recommendation != "keep" else 0
        confidence = policy.source_supported_confidence_percent if supported else (
            policy.strong_metadata_confidence_percent if removable_clusters else None
        )
        confidence_basis = (
            "configured source-supported metadata heuristic" if supported else
            "configured strong metadata heuristic" if removable_clusters else
            "unknown; no duplicate cleanup evidence"
        )
        risk_weight = policy.high_risk_weight if risk.risk == "high" else policy.unknown_risk_weight
        score = None if savings is None or confidence is None else savings * confidence // (100 * risk_weight)
        evidence = tuple(dict.fromkeys((*risk.reasons, decision, *(
            item for cluster in clusters for item in cluster.evidence
        ))))
        components = (
            ScoreComponent("estimated_savings_bytes", "unknown" if savings is None else str(savings),
                           "Whole-message provider estimate; zero for Keep/retained items."),
            ScoreComponent("confidence_percent", "unknown" if confidence is None else str(confidence), confidence_basis),
            ScoreComponent("risk_weight", str(risk_weight), f"Configured weight for {risk.risk} risk."),
            ScoreComponent("formula", "savings * confidence / (100 * risk_weight)",
                           "Integer ranking value; not measured bytes or a probability of safe removal."),
        )
        candidates.append(CleanupCandidate(
            message.ref, savings, confidence, confidence_basis, risk.risk,
            recommendation, score, evidence, retained, components,
        ))
    tier_order = {"safe": 0, "review": 1, "aggressive": 2, "keep": 3}
    candidates.sort(key=lambda item: (
        tier_order[item.recommendation], item.score is None,
        -(item.score or 0), item.message_ref,
    ))
    return CleanupPlan(duplicates, policy.version, tuple(candidates))
