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
    model: str = "explainable"
    conceptual_formula: str = "space_saved * confidence / risk"
    require_reason: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise PolicyError("Scoring policy version is invalid.")
        numeric = (
            self.source_supported_confidence_percent,
            self.strong_metadata_confidence_percent,
            self.high_risk_weight,
            self.unknown_risk_weight,
        )
        if any(type(value) is not int for value in numeric):
            raise PolicyError("Scoring policy contains a non-integer numeric value.")
        if not (0 < self.strong_metadata_confidence_percent
                <= self.source_supported_confidence_percent <= 100):
            raise PolicyError("Scoring confidence values are invalid.")
        if self.high_risk_weight < 1 or self.unknown_risk_weight < self.high_risk_weight:
            raise PolicyError("Scoring risk weights would weaken conservative handling.")
        if self.model != "explainable":
            raise PolicyError("Scoring policy model is unsupported.")
        if self.conceptual_formula != "space_saved * confidence / risk":
            raise PolicyError("Scoring policy formula is unsupported.")
        if self.require_reason is not True:
            raise PolicyError("Scoring policy must require reasons.")


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
    raw_values: dict[str, str] = {}
    numeric_keys = {
        "source_supported_confidence_percent",
        "strong_metadata_confidence_percent",
        "high_risk_weight",
        "unknown_risk_weight",
    }
    keys = numeric_keys | {"model", "conceptual_formula", "require_reason"}
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
            key, raw_value = key.strip(), raw_value.strip()
            if key not in keys:
                raise PolicyError("Scoring policy contains an unsupported key.")
            if key in raw_values:
                raise PolicyError("Scoring policy contains a duplicate key.")
            raw_values[key] = raw_value
    if not version or set(raw_values) != keys:
        raise PolicyError("Scoring policy is incomplete.")
    values: dict[str, int] = {}
    for key in numeric_keys:
        try:
            values[key] = int(raw_values[key])
        except ValueError:
            raise PolicyError("Scoring policy contains a non-integer numeric value.") from None
    formula = raw_values["conceptual_formula"]
    if len(formula) >= 2 and formula[0] == formula[-1] and formula[0] in "\"'":
        formula = formula[1:-1]
    return ScoringPolicy(
        version=version,
        **values,
        model=raw_values["model"],
        conceptual_formula=formula,
        require_reason=raw_values["require_reason"] == "true",
    )
