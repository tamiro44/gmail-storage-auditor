"""Strict loader for the small, versioned risk-policy surface."""

from dataclasses import dataclass
from pathlib import Path


class PolicyError(ValueError):
    """The checked-in policy is missing or unsafe to interpret."""


@dataclass(frozen=True)
class RiskPolicy:
    version: str
    protected_categories: tuple[str, ...]
    sentimental_default: str


@dataclass(frozen=True)
class ScoringPolicy:
    """Reviewed numeric inputs for ranking; recommendations remain safety-owned."""

    version: str
    source_supported_confidence_percent: int
    strong_metadata_confidence_percent: int
    high_risk_weight: int
    unknown_risk_weight: int


DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yaml"
REQUIRED_PROTECTED_CATEGORIES = frozenset(
    ("tax", "legal", "financial", "medical", "identity", "employment", "signed_documents")
)


def load_risk_policy(path: str | Path = DEFAULT_POLICY_PATH) -> RiskPolicy:
    """Read only the risk keys we own, without adding a YAML dependency.

    The repository policy uses scalar mappings.  Ambiguous or missing values fail
    closed instead of silently inventing less conservative defaults.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PolicyError("Risk policy could not be read.") from exc

    section = None
    version = None
    protected: list[str] = []
    sentimental = None
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if indent == 0:
            section = text[:-1] if text.endswith(":") else None
            if text.startswith("version:"):
                version = text.partition(":")[2].strip()
            continue
        if indent == 2 and ":" in text:
            key, _, value = text.partition(":")
            key, value = key.strip(), value.strip()
            if section == "protected_categories" and value == "protected":
                protected.append(key)
            elif section == "sentimental_media" and key == "default":
                sentimental = value

    if not version or not protected or sentimental != "review":
        raise PolicyError("Risk policy is incomplete or has unsupported safety defaults.")
    if len(set(protected)) != len(protected):
        raise PolicyError("Risk policy contains duplicate protected categories.")
    if not REQUIRED_PROTECTED_CATEGORIES.issubset(protected):
        raise PolicyError("Risk policy weakens a required protected category.")
    return RiskPolicy(version, tuple(protected), sentimental)


def load_scoring_policy(path: str | Path = DEFAULT_POLICY_PATH) -> ScoringPolicy:
    """Load the deliberately small numeric scoring surface and fail closed."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PolicyError("Scoring policy could not be read.") from exc
    version = None
    section = None
    values: dict[str, int] = {}
    keys = {
        "source_supported_confidence_percent",
        "strong_metadata_confidence_percent",
        "high_risk_weight",
        "unknown_risk_weight",
    }
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if indent == 0:
            section = text[:-1] if text.endswith(":") else None
            if text.startswith("version:"):
                version = text.partition(":")[2].strip()
        elif section == "scoring" and indent == 2 and ":" in text:
            key, _, raw_value = text.partition(":")
            if key in keys:
                try:
                    values[key] = int(raw_value.strip())
                except ValueError:
                    raise PolicyError("Scoring policy contains a non-integer numeric value.") from None
    if not version or set(values) != keys:
        raise PolicyError("Scoring policy is incomplete.")
    if not (0 < values["strong_metadata_confidence_percent"] <= values["source_supported_confidence_percent"] <= 100):
        raise PolicyError("Scoring confidence values are invalid.")
    if values["high_risk_weight"] < 1 or values["unknown_risk_weight"] < values["high_risk_weight"]:
        raise PolicyError("Scoring risk weights would weaken conservative handling.")
    return ScoringPolicy(version=version, **values)
