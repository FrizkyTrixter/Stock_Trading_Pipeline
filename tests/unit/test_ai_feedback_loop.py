from trading_system.ai_feedback_loop import (
    AIInfraCategory,
    build_category_targets,
    build_feedback_loop_rationale,
    classify_ai_infra_exposure,
)
from trading_system.config import AIInfrastructurePolicyConfig


def test_classify_ai_infra_exposure_detects_multiple_categories() -> None:
    facts = {
        "description": "GPU semiconductors and optical networking in hyperscale cloud"
    }
    categories = classify_ai_infra_exposure(facts)
    assert AIInfraCategory.CHIPS_SEMICONDUCTORS in categories
    assert AIInfraCategory.NETWORKING_INTERCONNECT in categories
    assert AIInfraCategory.CLOUD_HYPERSCALERS in categories


def test_build_category_targets_is_deterministic() -> None:
    config = AIInfrastructurePolicyConfig(
        enabled=True,
        categories=(
            AIInfraCategory.CHIPS_SEMICONDUCTORS.value,
            AIInfraCategory.CLOUD_HYPERSCALERS.value,
        ),
        target_counts={
            AIInfraCategory.CHIPS_SEMICONDUCTORS.value: 24,
            AIInfraCategory.CLOUD_HYPERSCALERS.value: 16,
        },
    )
    assert build_category_targets(config) == {
        AIInfraCategory.CHIPS_SEMICONDUCTORS: 24,
        AIInfraCategory.CLOUD_HYPERSCALERS: 16,
    }


def test_feedback_loop_rationale_is_deterministic() -> None:
    first = build_feedback_loop_rationale(
        ticker="NVDA",
        company_name="NVIDIA",
        categories=(
            AIInfraCategory.CHIPS_SEMICONDUCTORS.value,
            AIInfraCategory.NETWORKING_INTERCONNECT.value,
        ),
        thesis="accelerated compute demand",
    )
    second = build_feedback_loop_rationale(
        ticker="NVDA",
        company_name="NVIDIA",
        categories=(
            AIInfraCategory.CHIPS_SEMICONDUCTORS.value,
            AIInfraCategory.NETWORKING_INTERCONNECT.value,
        ),
        thesis="accelerated compute demand",
    )
    assert first == second
