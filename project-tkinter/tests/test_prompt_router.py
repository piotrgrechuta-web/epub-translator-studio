from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from translation_engine import (  # noqa: E402
    Segment,
    build_router_adjusted_prompt,
    classify_segment_class,
    route_prompt_strategy,
)


def _seg(text: str, idx: int = 1) -> Segment:
    return Segment(idx=idx, el=None, seg_id=f"s-{idx}", inner=text, plain=text)  # type: ignore[arg-type]


def test_classify_segment_class_dialogue_and_narrative() -> None:
    cls_dialog, conf_dialog = classify_segment_class('"- Where are you?" she asked.')
    cls_narr, conf_narr = classify_segment_class(
        "The corridor was narrow, damp, and full of old portraits; each frame reflected pale moonlight."
    )
    assert cls_dialog == "dialogue"
    assert conf_dialog >= 0.2
    assert cls_narr == "narrative"
    assert conf_narr >= 0.2


def test_route_prompt_strategy_falls_back_to_default_on_low_confidence() -> None:
    strategy, seg_class, conf = route_prompt_strategy([_seg("Alpha beta gamma")], fallback_threshold=0.95)
    assert seg_class in {"other", "mixed", "dialogue", "narrative"}
    assert conf <= 0.95
    assert strategy.id == "default"


def test_route_prompt_strategy_is_deterministic_for_same_input() -> None:
    batch = [_seg('"- Stop."'), _seg('"No."')]
    s1, c1, f1 = route_prompt_strategy(batch)
    s2, c2, f2 = route_prompt_strategy(batch)
    assert (s1.id, c1, round(f1, 4)) == (s2.id, c2, round(f2, 4))


def test_build_router_adjusted_prompt_includes_strategy_and_overlay() -> None:
    strategy, seg_class, conf = route_prompt_strategy([_seg("Narrative sample text with punctuation, commas, and flow.")])
    out = build_router_adjusted_prompt(
        "Base prompt.",
        strategy,
        segment_class=seg_class,
        confidence=conf,
        style_overlay="Fantasy style pack: preserve archaic cadence.",
    )
    assert "strategy_id:" in out
    assert "[Style Overlay]" in out
