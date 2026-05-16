from typing import Callable, Dict


def corridor_alignment_score(stop_corridor: str, bus_corridor_counts: Dict[str, int]) -> float:
    """Return [0..1] corridor alignment score based on bus serving history."""
    if not stop_corridor or not bus_corridor_counts:
        return 0.0
    total = sum(int(v) for v in bus_corridor_counts.values())
    if total <= 0:
        return 0.0
    return float(bus_corridor_counts.get(stop_corridor, 0)) / float(total)


def refresh_bus_state(
    bus_obj: Dict,
    bus_states: Dict[int, Dict],
    college_lat: float,
    college_lon: float,
    haversine_km: Callable[[float, float, float, float], float],
) -> Dict:
    """Recompute mutable per-bus state after chunk changes."""
    bus_number = int(bus_obj["bus_number"])
    corridor_counts: Dict[str, int] = {}
    assigned_stops = []
    farthest_km = 0.0
    for chunk_item in bus_obj["chunks"]:
        corridor_id = str(chunk_item.get("corridor", ""))
        if corridor_id:
            corridor_counts[corridor_id] = corridor_counts.get(corridor_id, 0) + int(
                chunk_item.get("student_count", 0)
            )
        sid = str(chunk_item.get("stop_id", ""))
        if sid:
            assigned_stops.append(sid)
        farthest_km = max(
            farthest_km,
            haversine_km(
                float(chunk_item["lat"]),
                float(chunk_item["lon"]),
                college_lat,
                college_lon,
            ),
        )
    seed = bus_states.get(bus_number, {}).get("cluster_seed")
    bus_states[bus_number] = {
        "corridor_counts": corridor_counts,
        "assigned_stops": assigned_stops,
        "farthest_km": float(farthest_km),
        "cluster_seed": seed,
    }
    return bus_states[bus_number]
