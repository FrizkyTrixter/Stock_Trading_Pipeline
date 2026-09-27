"""Narrative/audit helpers for the AI-investing-in-itself thesis.

AI investing in itself: invest in AI infrastructure stocks (chips, data centers,
cloud, AI model companies) as if AI is investing in itself, creating a feedback
loop where those stocks power the AI, the AI gets more powerful, it gets better
at investing, invests in itself more — an exponential loop.

# capital
#   -> AI infra equities
#   -> stronger AI ecosystem
#   -> better research + better investing
#   -> improved allocation
#   -> more capital

This module is deterministic and purely local (no randomness, no network, no
LLM calls). It is a narrative/audit construct and never bypasses UniversePolicy
eligibility, concentration, or governance gates.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any


class AIInfraCategory(StrEnum):
    CHIPS_SEMICONDUCTORS = "chips_semiconductors"
    DATA_CENTERS_COMPUTE = "data_centers_compute"
    CLOUD_HYPERSCALERS = "cloud_hyperscalers"
    AI_MODELS_LABS_PLATFORMS = "ai_models_labs_platforms"
    NETWORKING_INTERCONNECT = "networking_interconnect"
    POWER_ENERGY_FOR_AI = "power_energy_for_ai"


CATEGORY_DEFINITIONS: dict[AIInfraCategory, str] = {
    AIInfraCategory.CHIPS_SEMICONDUCTORS: (
        "Semiconductor design or manufacturing used for AI training and inference."
    ),
    AIInfraCategory.DATA_CENTERS_COMPUTE: (
        "Data-center capacity or compute infrastructure powering AI workloads."
    ),
    AIInfraCategory.CLOUD_HYPERSCALERS: (
        "Hyperscale cloud platforms hosting and distributing AI workloads."
    ),
    AIInfraCategory.AI_MODELS_LABS_PLATFORMS: (
        "AI model, lab, or software platform providers monetizing AI capability."
    ),
    AIInfraCategory.NETWORKING_INTERCONNECT: (
        "Networking or interconnect systems moving data across AI clusters."
    ),
    AIInfraCategory.POWER_ENERGY_FOR_AI: (
        "Power, grid, cooling, and energy systems enabling AI infrastructure."
    ),
}


FEEDBACK_LOOP_NARRATIVE = (
    "AI investing in itself: invest in AI infrastructure stocks (chips, data centers, "
    "cloud, AI model companies) as if AI is investing in itself, creating a feedback "
    "loop where those stocks power the AI, the AI gets more powerful, it gets better "
    "at investing, invests in itself more — an exponential loop."
)


_KEYWORDS: dict[AIInfraCategory, tuple[str, ...]] = {
    AIInfraCategory.CHIPS_SEMICONDUCTORS: (
        "chip",
        "semiconductor",
        "gpu",
        "cpu",
        "asic",
        "wafer",
        "foundry",
    ),
    AIInfraCategory.DATA_CENTERS_COMPUTE: (
        "data center",
        "server",
        "compute cluster",
        "hpc",
        "colocation",
    ),
    AIInfraCategory.CLOUD_HYPERSCALERS: (
        "cloud",
        "hyperscale",
        "iaas",
        "paas",
        "saas",
    ),
    AIInfraCategory.AI_MODELS_LABS_PLATFORMS: (
        "ai model",
        "foundation model",
        "llm",
        "generative ai",
        "machine learning platform",
        "copilot",
    ),
    AIInfraCategory.NETWORKING_INTERCONNECT: (
        "network",
        "ethernet",
        "switch",
        "router",
        "interconnect",
        "optical",
        "infiniband",
    ),
    AIInfraCategory.POWER_ENERGY_FOR_AI: (
        "power",
        "energy",
        "grid",
        "utility",
        "cooling",
        "nuclear",
        "renewable",
    ),
}


def _flatten(value: Any) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        values: list[str] = []
        for item in value.values():
            values.extend(_flatten(item))
        return values
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        values = []
        for item in value:
            values.extend(_flatten(item))
        return values
    return (str(value),)


def classify_ai_infra_exposure(security_facts: Mapping[str, Any]) -> set[AIInfraCategory]:
    """Classify AI-infrastructure exposure with deterministic keyword rules."""

    blob = " ".join(chunk.lower() for chunk in _flatten(security_facts))
    result: set[AIInfraCategory] = set()
    for category, tokens in _KEYWORDS.items():
        if any(token in blob for token in tokens):
            result.add(category)
    return result


def build_category_targets(config: Any) -> dict[AIInfraCategory, int]:
    """Build deterministic category targets from config categories/target_counts."""

    categories = tuple(getattr(config, "categories", (item.value for item in AIInfraCategory)))
    target_counts = dict(getattr(config, "target_counts", {}))
    selected = [AIInfraCategory(value) for value in categories]
    return {category: int(target_counts.get(category.value, 0)) for category in selected}


def build_feedback_loop_rationale(
    *,
    ticker: str,
    company_name: str,
    categories: Iterable[str],
    thesis: str,
) -> str:
    """Create deterministic one-line audit text for the loop narrative."""

    normalized = sorted(dict.fromkeys(item.strip() for item in categories if item.strip()))
    category_text = ", ".join(normalized) if normalized else "uncategorized"
    core_thesis = thesis.strip().rstrip(".")
    return (
        f"{ticker} ({company_name}) supports {category_text}; this compounds the AI feedback "
        f"loop through {core_thesis}."
    )
