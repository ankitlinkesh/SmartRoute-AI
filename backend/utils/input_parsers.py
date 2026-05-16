from __future__ import annotations

from typing import Dict, Optional


def is_no_constraint_value(raw_value: object) -> bool:
    if raw_value is None:
        return True
    text = str(raw_value).strip().lower()
    return text in {"", "none", "null", "- no constraints -", "no constraints"}


def coerce_optional_constraint(raw_value: object, fallback: Optional[int]) -> Optional[int]:
    if is_no_constraint_value(raw_value):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return fallback


def parse_optional_constraint_input(
    raw_value: object,
    default_value: Optional[int],
    minimum_value: int,
    field_label: str,
) -> Optional[int]:
    parsed = coerce_optional_constraint(raw_value, default_value)
    if parsed is None:
        return None
    if parsed < minimum_value:
        if minimum_value <= 0:
            raise ValueError(f"{field_label} must be {minimum_value} or greater.")
        raise ValueError(f"{field_label} must be greater than 0.")
    return parsed


def parse_per_bus_capacities(raw_value: object) -> Dict[int, int]:
    text = str(raw_value or "").strip()
    if not text:
        return {}
    capacities: Dict[int, int] = {}
    tokens = [token.strip() for token in text.replace("\n", ",").split(",") if token.strip()]
    for token in tokens:
        if ":" not in token:
            raise ValueError("Per-bus capacities must use `bus:capacity` format (example: 1:40,2:52).")
        bus_text, cap_text = [part.strip() for part in token.split(":", 1)]
        try:
            bus_number = int(bus_text.lower().replace("bus", "").strip())
            capacity = int(cap_text)
        except ValueError as exc:
            raise ValueError("Per-bus capacities must be whole numbers (example: 1:40,2:52).") from exc
        if bus_number <= 0 or capacity <= 0:
            raise ValueError("Per-bus bus numbers and capacities must be greater than 0.")
        capacities[int(bus_number)] = int(capacity)
    return capacities


def format_constraint_for_display(value: Optional[int], unit_label: str) -> str:
    if value is None:
        return "No Constraints"
    suffix = f" {unit_label}".strip()
    return f"{int(value)}{f' {suffix}' if suffix else ''}"

