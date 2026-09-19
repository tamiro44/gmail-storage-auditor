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


DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yaml"


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
    return RiskPolicy(version, tuple(protected), sentimental)
