"""Deterministic attachment metadata analysis; no read or action capabilities."""

from dataclasses import dataclass

from .inventory import Inventory, Message


@dataclass(frozen=True)
class DuplicateCluster:
    filename: str
    size_bytes: int
    members: tuple[str, ...]
    confidence: str
    evidence: tuple[str, ...]
    retained_ref: str
    retention_reason: str
    authority: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class DuplicateAnalysis:
    inventory: Inventory
    clusters: tuple[DuplicateCluster, ...]
    retained_refs: tuple[str, ...]


def _roles(message: Message) -> set[str]:
    # Exact source-supplied observations only; never parse subjects or filenames.
    return {hint.value for hint in message.hints} & {"original", "forwarded"}


def analyze_duplicates(inventory: Inventory) -> DuplicateAnalysis:
    """Group exact (case-sensitive filename, byte-size) keys across messages.

    Confidence describes metadata matching, not content identity or removability.
    Retained references are proposals for private review, never action targets.
    """
    groups: dict[tuple[str, int], dict[str, Message]] = {}
    for message in inventory.messages:
        for attachment in message.attachments:
            if attachment.filename is not None and attachment.size_bytes is not None:
                groups.setdefault((attachment.filename, attachment.size_bytes), {})[message.ref] = message

    clusters = []
    for (filename, size), by_ref in sorted(groups.items()):
        if len(by_ref) < 2:
            continue
        members = tuple(by_ref[ref] for ref in sorted(by_ref))
        evidence = ["exact_filename_and_byte_size"]
        limitations = [
            "Metadata equality does not prove identical attachment content.",
            "Message bodies and unique context are unverified; no whole-message removal is recommended.",
        ]
        originals = []
        for message in members:
            roles = _roles(message)
            for hint in sorted(message.hints, key=lambda hint: (hint.value, hint.source)):
                if hint.value in roles:
                    evidence.append(f"{message.ref}: {hint.value} (source: {hint.source})")
            if len(roles) > 1:
                limitations.append(f"{message.ref}: conflicting original/forwarded observations.")
            if message.direction in ("sent", "self_sent"):
                evidence.append(f"{message.ref}: {message.direction}_copy_pattern (normalized direction)")
            if roles == {"original"} and message.thread_ref is not None:
                forwards = [other for other in members if other.ref != message.ref
                            and other.thread_ref == message.thread_ref
                            and _roles(other) == {"forwarded"}]
                if forwards:
                    originals.append(message)
                    for forward in forwards:
                        evidence.append(f"same_thread_original_forward: {message.ref}, {forward.ref}")
        original_count = sum("original" in _roles(message) for message in members)
        if len(originals) == 1 and original_count == 1 and not any(len(_roles(message)) > 1 for message in members):
            retained = originals[0]
            authority = "source_supported"
            reason = "Only explicitly observed original with a matching forward in the same known thread."
        else:
            # A stable fallback preserves a copy without pretending age/direction
            # proves authorship. Conflicting/multiple originals remain unresolved.
            retained = members[0]
            authority = "unresolved"
            reason = "Stable reference fallback; available observations do not identify one authoritative original."
            limitations.append("Authoritative-copy identity requires review.")
        if any(message.attachments_complete is not True for message in members):
            limitations.append("Attachment enumeration is incomplete or unknown.")
        if not inventory.complete:
            limitations.append("Partial inventory: additional copies may be unobserved.")
        clusters.append(DuplicateCluster(
            filename, size, tuple(message.ref for message in members),
            "strong_metadata_match", tuple(evidence), retained.ref, reason,
            authority, tuple(limitations),
        ))
    result = tuple(clusters)
    return DuplicateAnalysis(inventory, result, tuple(sorted({c.retained_ref for c in result})))
