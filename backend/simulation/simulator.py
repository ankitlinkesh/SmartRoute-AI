from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np


def simulate_routes(
    *,
    current_routes: List[Dict],
    occupancy_percent: int,
    overflow_enabled: bool,
    overflow_limit: int,
    disabled_buses: List[int],
    bus_capacity: int,
    build_capacity_profile,
    max_ride_duration_minutes: Optional[int],
    stop_dwell_seconds: Optional[int],
    per_bus_actual_capacities: Optional[Dict[int, int]] = None,
) -> Dict:
    routes = [dict(route) for route in current_routes]
    disabled_set = {int(bus) for bus in disabled_buses}
    active_routes = [route for route in routes if int(route.get("bus_number", -1)) not in disabled_set]

    capacity_profile = build_capacity_profile(
        bus_capacity=bus_capacity,
        occupancy_percent=occupancy_percent,
        overflow_enabled=overflow_enabled,
        overflow_limit=overflow_limit,
    )
    planned_capacity = int(capacity_profile["planned_capacity"])
    usable_capacity = int(capacity_profile["usable_capacity"])

    current_students = sum(int(route.get("total_students", 0)) for route in active_routes)
    simulated_buses_used = min(
        max(1, len(active_routes)),
        int(math.ceil(current_students / max(1, usable_capacity))) if current_students > 0 else 0,
    )
    network_capacity = usable_capacity * max(1, simulated_buses_used)
    overflow_passengers = max(0, current_students - (planned_capacity * max(1, simulated_buses_used)))
    unassigned = max(0, current_students - network_capacity)
    overloaded_buses = max(0, simulated_buses_used - int(math.floor(current_students / max(1, usable_capacity))))

    avg_duration = (
        sum(float(route.get("route_duration_min", 0.0)) for route in active_routes) / len(active_routes)
        if active_routes
        else 0.0
    )
    avg_distance = (
        sum(float(route.get("route_distance_km", 0.0)) for route in active_routes) / len(active_routes)
        if active_routes
        else 0.0
    )
    per_bus_map = per_bus_actual_capacities or {}
    active_capacity_total = 0
    for route in active_routes:
        bus_num = int(route.get("bus_number", 0))
        active_capacity_total += max(1, int(per_bus_map.get(bus_num, route.get("actual_capacity", bus_capacity))))
    average_occupancy = (
        (current_students / max(1, active_capacity_total)) * 100.0
        if simulated_buses_used > 0
        else 0.0
    )
    duration_penalty = (
        max(0.0, avg_duration - float(max_ride_duration_minutes)) * 0.7
        if max_ride_duration_minutes is not None
        else 0.0
    )
    route_efficiency_score = max(
        0.0,
        100.0 - (duration_penalty + (max(0.0, average_occupancy - 100.0) * 0.5)),
    )

    warnings: List[str] = []
    if unassigned > 0:
        warnings.append("Simulation detected unassigned students due to reduced capacity.")
    if overloaded_buses > 0:
        warnings.append("Simulation detected overloaded buses.")
    if max_ride_duration_minutes is not None and avg_duration > float(max_ride_duration_minutes):
        warnings.append("Simulation indicates ride duration may exceed configured limit.")

    return {
        "routes": active_routes,
        "metrics": {
            "buses_used": int(simulated_buses_used),
            "avg_travel_time": round(avg_duration, 1),
            "avg_distance": round(avg_distance, 2),
            "overflow_passengers": int(overflow_passengers),
            "unassigned_students": int(unassigned),
            "overloaded_buses": int(overloaded_buses),
            "occupancy_percent": int(occupancy_percent),
            "overflow_enabled": bool(overflow_enabled),
            "overflow_limit": int(overflow_limit),
            "planned_capacity": int(planned_capacity),
            "overflow_capacity": int(capacity_profile["overflow_capacity"]),
            "usable_capacity": int(usable_capacity),
            "bus_reduction": max(0, len(active_routes) - int(simulated_buses_used)),
            "max_ride_duration_minutes": None if max_ride_duration_minutes is None else int(max_ride_duration_minutes),
            "stop_dwell_seconds": None if stop_dwell_seconds is None else int(stop_dwell_seconds),
            "average_occupancy": round(average_occupancy, 1),
            "route_efficiency_score": round(route_efficiency_score, 1),
            "longest_ride_duration": round(
                max((float(route.get("route_duration_min", 0.0)) for route in active_routes), default=0.0), 1
            ),
        },
        "warnings": warnings,
    }

