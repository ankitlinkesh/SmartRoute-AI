from __future__ import annotations

from typing import Dict, List


def summarize_health_state(score: float) -> str:
    if score >= 70:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def apply_penalty(score: float, penalties: List[Dict], category: str, points: float, message: str) -> float:
    penalties.append(
        {
            "category": category,
            "points": round(points, 1),
            "message": message,
        }
    )
    return score - points


