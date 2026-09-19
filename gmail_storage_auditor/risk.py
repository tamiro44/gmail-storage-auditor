"""Explainable, conservative risk classification over normalized observations."""

from dataclasses import dataclass
from typing import Protocol

from .duplicates import DuplicateAnalysis
from .inventory import Inventory, Message
from .policy import RiskPolicy, load_risk_policy


@dataclass(frozen=True)
class RiskFinding:
    category: str
    evidence: str
    source: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.category, "category"),
            (self.evidence, "evidence"),
            (self.source, "source"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Risk finding {field} must be a non-empty string.")


class SemanticClassifier(Protocol):
    """Optional advisory classifier. It has no action or policy capability."""

    def classify(self, message: Message) -> tuple[RiskFinding, ...]: ...


@dataclass(frozen=True)
class RiskClassification:
    message_ref: str
    risk: str
    recommendation: str
    categories: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence: tuple[RiskFinding, ...]
    duplicate_clusters: tuple[str, ...]


def _supplied_findings(message: Message, policy: RiskPolicy) -> tuple[RiskFinding, ...]:
    recognized = set(policy.protected_categories) | {"sentimental_media"}
    return tuple(
        RiskFinding(hint.value, f"Supplied category hint from {hint.source}.", hint.source)
        for hint in message.hints if hint.value in recognized
    )


def classify_risk(
    inventory: Inventory,
    duplicates: DuplicateAnalysis | None = None,
    *,
    policy: RiskPolicy | None = None,
    semantic_classifier: SemanticClassifier | None = None,
) -> tuple[RiskClassification, ...]:
    """Classify every observation; optional semantics can only add risk.

    Hints are normalized, source-supplied evidence. Semantic implementations are
    explicitly injected and receive one normalized record at a time. Their output
    cannot establish duplication, authoritative retention, or a Safe result.
    """
    policy = policy or load_risk_policy()
    if duplicates is not None and duplicates.inventory != inventory:
        raise ValueError("Duplicate analysis must belong to the classified inventory.")
    protected = set(policy.protected_categories)
    clusters_by_ref: dict[str, list] = {}
    for cluster in (() if duplicates is None else duplicates.clusters):
        for ref in cluster.members:
            clusters_by_ref.setdefault(ref, []).append(cluster)

    results = []
    for message in inventory.messages:
        findings = list(_supplied_findings(message, policy))
        if semantic_classifier is not None:
            try:
                semantic = semantic_classifier.classify(message)
                if not isinstance(semantic, tuple) or any(not isinstance(x, RiskFinding) for x in semantic):
                    raise TypeError
                findings.extend(semantic)
            except Exception:
                findings.append(RiskFinding("classification_uncertain", "Optional semantic classification was unavailable or invalid.", "semantic_classifier"))

        if not findings:
            findings.append(RiskFinding(
                "unclassified",
                "Available normalized metadata supplied no recognized risk category.",
                "deterministic_policy",
            ))

        categories = tuple(sorted({f.category for f in findings}))
        is_protected = any(category in protected for category in categories)
        sentimental = "sentimental_media" in categories
        uncertain = "classification_uncertain" in categories
        clusters = clusters_by_ref.get(message.ref, [])
        authoritative_duplicate = any(
            cluster.authority == "source_supported" and cluster.retained_ref != message.ref
            for cluster in clusters
        )

        reasons = []
        if is_protected:
            reasons.append("Protected category requires conservative retention.")
            recommendation, risk = ("review", "high") if authoritative_duplicate else ("keep", "high")
        elif sentimental:
            reasons.append("Sentimental media defaults to Review under policy.")
            recommendation, risk = "review", "high"
        elif uncertain:
            reasons.append("Classification uncertainty prevents a low-risk conclusion.")
            recommendation, risk = "review", "unknown"
        else:
            reasons.append("No protected category was recognized; missing context still requires review.")
            recommendation, risk = "review", "unknown"
        if clusters:
            reasons.append("Duplicate metadata was recognized but does not prove whole-message redundancy.")
        if authoritative_duplicate:
            reasons.append("A source-supported retained original exists; classification still remains conservative Review.")
        results.append(RiskClassification(
            message.ref, risk, recommendation, categories, tuple(reasons), tuple(findings),
            tuple(f"{cluster.filename}:{cluster.size_bytes}" for cluster in clusters),
        ))
    return tuple(results)
