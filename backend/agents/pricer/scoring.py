"""Pure scoring helpers — unit-testable, no I/O.

Score a listing against a median comp price and return a 0-100 score plus a
human-friendly label. Coordinator turns these into "GREAT DEAL / FAIR /
ABOVE MARKET" badges in the chat reply.
"""

from typing import Any

# Score thresholds. Pricing is a sliding scale around the median: at the
# median you sit at 50; further below pulls you toward 100, above pulls you
# toward 0. With sparse data (2 listings per category in the seed) the
# median is exactly between the two prices — every cheaper listing comes
# in around 20-30% below median. Tuned so that maps to "great_deal".
_GREAT_DEAL_MIN = 58
_FAIR_MIN = 42


def score_listing(price: float | None, median: float | None) -> dict[str, Any]:
    """Score a single listing's price against a median comp.

    Returns: {"deal_score": int|None, "label": str, "pct_below_median": float|None}.
    deal_score is None when there's no comp, score otherwise. Label is one
    of: "great_deal" | "fair" | "above_market" | "no_comp".
    """
    if price is None or median is None or median <= 0:
        return {"deal_score": None, "label": "no_comp", "pct_below_median": None}

    # pct of median: positive → cheaper than median; negative → more expensive.
    pct = (median - float(price)) / float(median)
    # Clamp to [-1, 1] so a freebie or a 10x outlier doesn't blow up the score.
    pct = max(-1.0, min(1.0, pct))
    score = round(50 + pct * 50)

    if score >= _GREAT_DEAL_MIN:
        label = "great_deal"
    elif score >= _FAIR_MIN:
        label = "fair"
    else:
        label = "above_market"

    return {
        "deal_score": int(score),
        "label": label,
        "pct_below_median": round(pct * 100, 1),
    }


def median(values: list[float], *, min_price: float = 5.0) -> float | None:
    """Plain median; None for empty input. Drops sub-$5 outliers so that
    junk/bundle listings ('$1 see all pictures') don't pull the comp
    median to the floor and make every real listing look 'above market'."""
    nums = sorted(
        float(v) for v in values
        if isinstance(v, (int, float)) and float(v) >= min_price
    )
    if not nums:
        return None
    n = len(nums)
    mid = n // 2
    if n % 2 == 1:
        return float(nums[mid])
    return float((nums[mid - 1] + nums[mid]) / 2.0)
