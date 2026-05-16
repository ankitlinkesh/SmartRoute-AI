from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def route_quality_metrics(
    routed_buses: List[Dict],
    assigned_students_df: pd.DataFrame,
    bus_capacity: int,
    max_ride_duration_minutes: Optional[int],
    haversine_km: Callable[[float, float, float, float], float],
    college_lat: float,
    college_lon: float,
    segment_overlap_score: Callable[[List[Dict], List[Dict]], float],
    summarize_health_state: Callable[[float], str],
    apply_penalty: Callable[[float, List[Dict], str, float, str], float],
) -> Tuple[List[str], Dict]:
    """Compute per-bus and global quality diagnostics for optimized routes."""
    warnings: List[str] = []
    walk_lookup = assigned_students_df.groupby("stop_id")["walk_distance_km"].mean().to_dict()

    per_bus: List[Dict] = []
    total_overlap = 0.0
    pair_count = 0
    compactness_values: List[float] = []
    longest_ride = 0.0
    overlap_by_bus: Dict[int, List[float]] = {
        int(bus["bus_number"]): [] for bus in routed_buses
    }

    base_metrics: List[Dict] = []
    for bus in routed_buses:
        stops = bus.get("ordered_stops", [])
        stop_count = len(stops)
        if stop_count > 1:
            spacings = [
                haversine_km(stops[i]["lat"], stops[i]["lon"], stops[i + 1]["lat"], stops[i + 1]["lon"])
                for i in range(stop_count - 1)
            ]
            avg_spacing = float(np.mean(spacings))
        else:
            avg_spacing = 0.0

        coords = [(float(stop["lat"]), float(stop["lon"])) for stop in stops]
        if coords:
            diameter = max(
                haversine_km(a[0], a[1], b[0], b[1])
                for a in coords for b in coords
            ) or 0.1
        else:
            diameter = 0.1
        compactness = float(bus.get("route_distance_km", 0.0)) / max(0.1, diameter)
        compactness_values.append(compactness)

        stop_ids = [str(stop.get("stop_id", "")) for stop in stops]
        walk_values = [float(walk_lookup.get(stop_id, 0.0)) for stop_id in stop_ids if stop_id in walk_lookup]
        avg_walk_km = float(np.mean(walk_values)) if walk_values else 0.0

        ride_duration = float(bus.get("route_duration_min", 0.0))
        longest_ride = max(longest_ride, ride_duration)
        capacity_for_bus = int(bus.get("actual_capacity", bus_capacity))
        occupancy_ratio = float(bus.get("total_students", 0)) / max(1, capacity_for_bus)
        farthest_college_distance = max(
            [
                haversine_km(float(stop["lat"]), float(stop["lon"]), college_lat, college_lon)
                for stop in stops
            ] or [0.1]
        )
        detour_index = float(bus.get("route_distance_km", 0.0)) / max(0.1, farthest_college_distance)

        base_metrics.append(
            {
                "bus_number": int(bus["bus_number"]),
                "stop_count": int(stop_count),
                "average_stop_spacing_km": round(avg_spacing, 2),
                "compactness": round(compactness, 2),
                "average_walk_distance_km": round(avg_walk_km, 2),
                "estimated_ride_duration_min": round(ride_duration, 1),
                "occupancy_ratio": round(occupancy_ratio * 100, 1),
                "detour_index": round(detour_index, 2),
                "route_distance_km": round(float(bus.get("route_distance_km", 0.0)), 2),
            }
        )

    for i in range(len(routed_buses)):
        for j in range(i + 1, len(routed_buses)):
            overlap = segment_overlap_score(
                routed_buses[i].get("ordered_stops", []),
                routed_buses[j].get("ordered_stops", []),
            )
            total_overlap += overlap
            pair_count += 1
            left_bus = int(routed_buses[i]["bus_number"])
            right_bus = int(routed_buses[j]["bus_number"])
            overlap_by_bus[left_bus].append(overlap)
            overlap_by_bus[right_bus].append(overlap)

    healthy_count = 0
    caution_count = 0
    severe_count = 0
    route_scores: List[float] = []

    for metric in base_metrics:
        score = 100.0
        penalties: List[Dict] = []
        ride_duration = float(metric["estimated_ride_duration_min"])
        compactness = float(metric["compactness"])
        avg_spacing = float(metric["average_stop_spacing_km"])
        occupancy_percent = float(metric["occupancy_ratio"])
        detour_index = float(metric["detour_index"])
        stop_count = int(metric["stop_count"])
        route_distance_km = float(metric["route_distance_km"])
        average_overlap = float(np.mean(overlap_by_bus.get(metric["bus_number"], [0.0])) if overlap_by_bus.get(metric["bus_number"]) else 0.0)

        if max_ride_duration_minutes is not None:
            duration_ratio = ride_duration / max(1.0, float(max_ride_duration_minutes))
            if duration_ratio >= 1.35:
                score = apply_penalty(score, penalties, "ride_duration", 34, "Ride duration is far above the configured limit.")
            elif duration_ratio >= 1.15:
                score = apply_penalty(score, penalties, "ride_duration", 18, "Ride duration is running longer than preferred.")
            elif duration_ratio >= 1.0:
                score = apply_penalty(score, penalties, "ride_duration", 8, "Ride duration is approaching the configured limit.")

        if compactness >= 4.8:
            score = apply_penalty(score, penalties, "compactness", 26, "Route compactness is very low for this service area.")
        elif compactness >= 3.7:
            score = apply_penalty(score, penalties, "compactness", 14, "Route compactness is below target and may indicate fragmentation.")
        elif compactness >= 2.8:
            score = apply_penalty(score, penalties, "compactness", 6, "Route compactness is slightly weaker than ideal.")

        if average_overlap >= 0.75:
            score = apply_penalty(score, penalties, "overlap", 24, "Severe route overlap detected with nearby buses.")
        elif average_overlap >= 0.45:
            score = apply_penalty(score, penalties, "overlap", 12, "Moderate route overlap detected.")
        elif average_overlap >= 0.25:
            score = apply_penalty(score, penalties, "overlap", 5, "Minor route overlap present.")

        if avg_spacing >= 7.0:
            score = apply_penalty(score, penalties, "stop_spacing", 18, "Stop spacing is excessive across the route.")
        elif avg_spacing >= 5.0:
            score = apply_penalty(score, penalties, "stop_spacing", 9, "Stop spacing is slightly high.")
        elif avg_spacing >= 3.8:
            score = apply_penalty(score, penalties, "stop_spacing", 4, "Stop spacing is trending sparse.")

        if detour_index >= 3.6:
            score = apply_penalty(score, penalties, "excessive_detour", 16, "Route detour is high relative to direct campus approach.")
        elif detour_index >= 2.8:
            score = apply_penalty(score, penalties, "excessive_detour", 8, "Route detour is moderately elevated.")
        elif detour_index >= 2.2:
            score = apply_penalty(score, penalties, "excessive_detour", 3, "Route detour is slightly above ideal.")

        if occupancy_percent >= 118:
            score = apply_penalty(score, penalties, "occupancy_imbalance", 16, "Occupancy is severely above standard operating target.")
        elif occupancy_percent >= 102:
            score = apply_penalty(score, penalties, "occupancy_imbalance", 8, "Occupancy is moderately above target.")
        elif stop_count > 0 and occupancy_percent <= 45 and route_distance_km >= 12:
            score = apply_penalty(score, penalties, "occupancy_imbalance", 6, "Route coverage is long for a relatively light load.")

        if stop_count <= 2 and route_distance_km >= 18:
            score = apply_penalty(score, penalties, "sparse_routing", 15, "Too few stops are spread over a long route.")
        elif stop_count <= 3 and route_distance_km >= 12:
            score = apply_penalty(score, penalties, "sparse_routing", 8, "Stop distribution is sparse for the distance covered.")

        score = max(0.0, score)
        health = summarize_health_state(score)
        if health == "green":
            healthy_count += 1
        elif health == "yellow":
            caution_count += 1
        else:
            severe_count += 1

        route_scores.append(score)
        metric["overlap_score"] = round(average_overlap, 3)
        metric["health_score"] = round(score, 1)
        metric["health"] = health
        metric["status_label"] = {
            "green": "Healthy",
            "yellow": "Caution",
            "red": "Severe",
        }[health]
        metric["warnings"] = [item["message"] for item in penalties]
        metric["penalties"] = penalties
        metric["primary_reason"] = penalties[0]["message"] if penalties else "Route is operating within acceptable thresholds."
        per_bus.append(metric)

    average_overlap = total_overlap / pair_count if pair_count else 0.0
    average_compactness = float(np.mean(compactness_values)) if compactness_values else 0.0
    average_occupancy = float(
        np.mean([item["occupancy_ratio"] for item in per_bus]) if per_bus else 0.0
    )
    efficiency_score = float(np.mean(route_scores)) if route_scores else 100.0

    if severe_count > 0:
        warnings.append(f"{severe_count} route{'s' if severe_count != 1 else ''} need immediate review due to combined quality issues.")
    if caution_count > 0:
        warnings.append(f"{caution_count} route{'s' if caution_count != 1 else ''} have caution-level quality warnings.")
    if average_overlap > 0.75:
        warnings.append("Network overlap is high across several routes.")
    if max_ride_duration_minutes is not None and longest_ride > float(max_ride_duration_minutes) * 1.2:
        warnings.append("Some rides are materially above the configured duration target.")

    return warnings, {
        "per_bus": per_bus,
        "global": {
            "total_overlap_score": round(average_overlap, 3),
            "average_route_compactness": round(average_compactness, 2),
            "average_occupancy": round(average_occupancy, 1),
            "route_efficiency_score": round(efficiency_score, 1),
            "longest_ride_duration": round(longest_ride, 1),
            "healthy_route_count": int(healthy_count),
            "caution_route_count": int(caution_count),
            "severe_route_count": int(severe_count),
        },
    }
