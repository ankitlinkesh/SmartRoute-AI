from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd


def write_project_artifacts(
    *,
    project_path: Path,
    sanitized_name: str,
    merged_students,
    assignments,
    buses,
    map_data,
    upload_summary: Dict,
    metrics: Dict,
    config_state: Dict,
    simulation_state: Dict,
    manual_plan_state: Dict,
    warnings,
) -> None:
    project_path.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(merged_students).to_csv(project_path / "merged_students.csv", index=False)
    pd.DataFrame(assignments).to_csv(project_path / "assignments.csv", index=False)

    routes_json = {
        "buses": buses,
        "map_data": map_data,
        "warnings": warnings,
        "manual_plan_state": manual_plan_state,
    }
    (project_path / "routes.json").write_text(json.dumps(routes_json, indent=2), encoding="utf-8")

    config_json = {
        "project_name": sanitized_name,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "occupancy_percent": int(config_state.get("occupancy_percent", 90)),
        "overflow_enabled": bool(config_state.get("overflow_enabled", False)),
        "overflow_limit": int(config_state.get("overflow_limit", 0)),
        "bus_capacity": int(config_state.get("bus_capacity", 0)),
        "per_bus_actual_capacities": {
            str(k): int(v)
            for k, v in (config_state.get("per_bus_actual_capacities", {}) or {}).items()
            if str(k).strip() and int(v) > 0
        },
        "arrival_time": str(config_state.get("arrival_time", "08:30")),
        "max_ride_duration_minutes": config_state.get("max_ride_duration_minutes"),
        "stop_dwell_seconds": config_state.get("stop_dwell_seconds"),
        "uploaded_files": int(upload_summary.get("uploaded_files", 0)),
        "invalid_rows_removed": int(upload_summary.get("invalid_rows_removed", 0)),
        "duplicate_students_removed": int(upload_summary.get("duplicate_students_removed", 0)),
        "simulation_state": simulation_state,
    }
    (project_path / "config.json").write_text(json.dumps(config_json, indent=2), encoding="utf-8")

    metrics_json = {
        "total_buses_used": int(metrics.get("total_buses_used", 0)),
        "average_travel_duration": float(metrics.get("average_travel_duration", 0)),
        "average_travel_distance": float(metrics.get("average_travel_distance", 0)),
        "total_route_distance": float(metrics.get("total_route_distance", 0)),
        "overload_percent": float(metrics.get("overload_percent", 0)),
        "overflow_passengers": int(metrics.get("overflow_passengers", 0)),
        "unused_capacity": int(metrics.get("unused_capacity", 0)),
        "total_students": int(metrics.get("total_students", len(merged_students))),
        "total_candidate_stops": int(metrics.get("total_candidate_stops", 0)),
        "matrix_source": str(metrics.get("matrix_source", "osrm")),
        "stop_source": str(metrics.get("stop_source", "mtc")),
        "required_buses_without_overflow": int(
            metrics.get("required_buses_without_overflow", metrics.get("total_buses_used", 0))
        ),
        "required_buses_with_current_capacity": int(
            metrics.get("required_buses_with_current_capacity", metrics.get("total_buses_used", 0))
        ),
        "bus_reduction_from_overflow": int(metrics.get("bus_reduction_from_overflow", 0)),
        "quality_metrics": metrics.get(
            "quality_metrics",
            {
                "per_bus": [],
                "global": {
                    "total_overlap_score": 0,
                    "average_route_compactness": 0,
                    "average_occupancy": 0,
                    "route_efficiency_score": 0,
                    "longest_ride_duration": 0,
                    "healthy_route_count": 0,
                    "caution_route_count": 0,
                    "severe_route_count": 0,
                },
            },
        ),
    }
    (project_path / "metrics.json").write_text(json.dumps(metrics_json, indent=2), encoding="utf-8")

