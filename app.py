from __future__ import annotations

import math
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, flash, render_template, request, jsonify, url_for
from sklearn.cluster import MiniBatchKMeans
from sklearn.neighbors import BallTree
from backend.utils.input_parsers import (
    coerce_optional_constraint as parser_coerce_optional_constraint,
    format_constraint_for_display as parser_format_constraint_for_display,
    is_no_constraint_value as parser_is_no_constraint_value,
    parse_optional_constraint_input as parser_parse_optional_constraint_input,
    parse_per_bus_capacities as parser_parse_per_bus_capacities,
)
from backend.utils.project_paths import (
    project_dir_for_name as util_project_dir_for_name,
    sanitize_project_name as util_sanitize_project_name,
)
from backend.persistence.driver_sheets import write_driver_sheets as persistence_write_driver_sheets
from backend.persistence.projects import (
    load_project_payload as persistence_load_project_payload,
    project_cards as persistence_project_cards,
)
from backend.persistence.exports import write_project_artifacts as persistence_write_project_artifacts
from backend.services.osrm_service import (
    get_osrm_table_block as service_get_osrm_table_block,
    get_osrm_table_matrix as service_get_osrm_table_matrix,
    osrm_get_json as service_osrm_get_json,
)
from backend.diagnostics.route_quality import (
    apply_penalty as diagnostics_apply_penalty,
    summarize_health_state as diagnostics_summarize_health_state,
)
from backend.diagnostics.metrics import route_quality_metrics as diagnostics_route_quality_metrics
from backend.simulation.simulator import simulate_routes as simulation_simulate_routes
from backend.preprocessing.validation import (
    get_student_column_mapping as preprocessing_get_student_column_mapping,
    merge_uploaded_student_csvs as preprocessing_merge_uploaded_student_csvs,
    normalize_student_column_name as preprocessing_normalize_student_column_name,
    parse_student_csv as preprocessing_parse_student_csv,
)
from backend.preprocessing.stop_generation import (
    build_stops_for_source as preprocessing_build_stops_for_source,
    generate_candidate_stops_500m as preprocessing_generate_candidate_stops_500m,
    load_mtc_stops as preprocessing_load_mtc_stops,
)
from backend.routing.route_sequencing import (
    estimate_route_shape_cost as routing_estimate_route_shape_cost,
    nearest_neighbor_route_by_time as routing_nearest_neighbor_route_by_time,
    optimize_stop_order_with_ortools as routing_optimize_stop_order_with_ortools,
    refine_stop_order_directional as routing_refine_stop_order_directional,
)
from backend.routing.capacity_assignment import (
    corridor_alignment_score as routing_corridor_alignment_score,
    refresh_bus_state as routing_refresh_bus_state,
)

try:
    from ortools.constraint_solver import routing_enums_pb2
    from ortools.constraint_solver import pywrapcp
    ORTOOLS_AVAILABLE = True
except Exception:
    ORTOOLS_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "smartroute-dev-secret")

# Campus and scheduling configuration.
COLLEGE_NAME = os.getenv("COLLEGE_NAME", "College Campus")
COLLEGE_LAT = float(os.getenv("COLLEGE_LAT", "34.0689"))
COLLEGE_LON = float(os.getenv("COLLEGE_LON", "-118.4452"))
BASE_ARRIVAL_TIME = os.getenv("BASE_ARRIVAL_TIME", "08:30")
ARRIVAL_STAGGER_MINUTES = int(os.getenv("ARRIVAL_STAGGER_MINUTES", "5"))
FALLBACK_AVERAGE_SPEED_KMH = float(os.getenv("FALLBACK_AVERAGE_SPEED_KMH", "30"))

# Public OSRM configuration and request safety controls.
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
OSRM_TIMEOUT_SECONDS = int(os.getenv("OSRM_TIMEOUT_SECONDS", "20"))
OSRM_MAX_RETRIES = int(os.getenv("OSRM_MAX_RETRIES", "3"))
OSRM_CALL_DELAY_SECONDS = float(os.getenv("OSRM_CALL_DELAY_SECONDS", "0.05"))
OSRM_COOLDOWN_SECONDS = int(os.getenv("OSRM_COOLDOWN_SECONDS", "60"))
_osrm_down_until = 0.0
OSRM_TABLE_BATCH_SIZE = int(os.getenv("OSRM_TABLE_BATCH_SIZE", "40"))
STOP_SPACING_KM = 0.5
TARGET_OCCUPANCY_RATIO = 0.9
BOARDING_SECONDS_PER_STUDENT = 4
MORNING_TRAFFIC_MULTIPLIER = 1.35
DEFAULT_STOP_SOURCE = "mtc"
ROUTES_PER_PAGE = 20
DEFAULT_MAX_RIDE_DURATION_MINUTES = int(os.getenv("DEFAULT_MAX_RIDE_DURATION_MINUTES", "120"))
DEFAULT_STOP_DWELL_SECONDS = int(os.getenv("DEFAULT_STOP_DWELL_SECONDS", "20"))
CORRIDOR_SECTOR_MIN = int(os.getenv("CORRIDOR_SECTOR_MIN", "2"))
CORRIDOR_SECTOR_MAX = int(os.getenv("CORRIDOR_SECTOR_MAX", "8"))
ASSIGNMENT_MAX_DETOUR_KM = float(os.getenv("ASSIGNMENT_MAX_DETOUR_KM", "10.0"))
ASSIGNMENT_MAX_STRETCH_RATIO = float(os.getenv("ASSIGNMENT_MAX_STRETCH_RATIO", "3.0"))
BUS_ACCESS_MAX_WALK_KM = float(os.getenv("BUS_ACCESS_MAX_WALK_KM", "2.0"))
BUS_ACCESS_NEAR_SUPPORT_M = float(os.getenv("BUS_ACCESS_NEAR_SUPPORT_M", "160"))
BUS_ACCESS_WIDE_SUPPORT_M = float(os.getenv("BUS_ACCESS_WIDE_SUPPORT_M", "360"))
BUS_ACCESS_MIN_WALK_M = float(os.getenv("BUS_ACCESS_MIN_WALK_M", "150"))
BUS_ACCESS_MAX_WALK_M = float(os.getenv("BUS_ACCESS_MAX_WALK_M", "2000"))
ROUTE_SHAPE_2OPT_MAX_PASSES = int(os.getenv("ROUTE_SHAPE_2OPT_MAX_PASSES", "2"))
ROUTE_SHAPE_2OPT_MAX_SWAPS = int(os.getenv("ROUTE_SHAPE_2OPT_MAX_SWAPS", "48"))
MTC_STOPS_PATH = Path("data") / "mtc_stops.csv"
ASSIGNMENTS_CSV_PATH = Path("static") / "assignments.csv"
PROJECTS_ROOT = Path("projects")
FLEET_CSV_PATH = Path("data") / "bus_fleet.csv"
FLEET_COLUMNS = [
    "bus_number",
    "registration_number",
    "seating_capacity",
    "last_service_date",
    "next_service_due",
    "insurance_last_renewed",
    "insurance_expiry",
    "fc_last_done",
    "fc_expiry",
    "tax_last_paid",
    "tax_expiry",
    "notes",
]
STUDENT_COLUMN_ALIASES = {
    "student_name": {"student_name", "name"},
    "latitude": {"latitude", "lat"},
    "longitude": {"longitude", "lon", "lng"},
}
STUDENT_EXPORT_COLUMNS = [
    "student_name",
    "stop_name",
    "bus_number",
    "pickup_time",
    "source_file",
]

DEFAULT_ROUTING_POLICY = os.getenv("DEFAULT_ROUTING_POLICY", "balanced")
ROUTING_POLICY_OPTIONS = {
    "strict_main_road": "Strict Main Road",
    "balanced": "Balanced",
    "coverage_priority": "Coverage Priority",
}


def normalize_routing_policy(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in ROUTING_POLICY_OPTIONS else "balanced"


def routing_policy_profile(policy_name: str) -> Dict[str, object]:
    policy = normalize_routing_policy(policy_name)
    profiles: Dict[str, Dict[str, object]] = {
        "strict_main_road": {
            "allow_residential": False,
            "allow_internal": False,
            "max_walk_km": None,
            "hard_directional": True,
            "outward_tolerance_km": 0.08,
            "road_penalties": {
                "primary": 0.0,
                "secondary": 0.4,
                "tertiary": 0.9,
                "residential": 7.0,
                "service/internal": 11.0,
            },
        },
        "balanced": {
            "allow_residential": True,
            "allow_internal": False,
            "max_walk_km": None,
            "hard_directional": True,
            "outward_tolerance_km": 0.18,
            "road_penalties": {
                "primary": 0.0,
                "secondary": 0.5,
                "tertiary": 0.95,
                "residential": 2.1,
                "service/internal": 4.0,
            },
        },
        "coverage_priority": {
            "allow_residential": True,
            "allow_internal": True,
            "max_walk_km": None,
            "hard_directional": True,
            "outward_tolerance_km": 0.35,
            "road_penalties": {
                "primary": 0.0,
                "secondary": 0.4,
                "tertiary": 0.8,
                "residential": 1.0,
                "service/internal": 1.6,
            },
        },
    }
    return {"name": policy, **profiles[policy]}

def sanitize_project_name(project_name: str) -> str:
    """Sanitize project name for filesystem-safe folder names."""
    return util_sanitize_project_name(project_name)


def project_dir_for_name(project_name: str) -> Path:
    """Return canonical project directory path under projects/ root."""
    return util_project_dir_for_name(PROJECTS_ROOT, project_name)


def format_pickup_window(time_text: str, spread_minutes: int = 3) -> str:
    """Create a compact pickup window label around a base HH:MM time."""
    try:
        center = datetime.strptime(str(time_text), "%H:%M")
    except ValueError:
        return ""
    start = (center - timedelta(minutes=spread_minutes)).strftime("%H:%M")
    end = (center + timedelta(minutes=spread_minutes)).strftime("%H:%M")
    return f"{start}-{end}"


def is_no_constraint_value(raw_value: object) -> bool:
    """Return True when a raw value represents an explicit no-constraint choice."""
    return parser_is_no_constraint_value(raw_value)


def coerce_optional_constraint(raw_value: object, fallback: Optional[int]) -> Optional[int]:
    """Coerce raw config/API constraint value to Optional[int] with safe fallback."""
    return parser_coerce_optional_constraint(raw_value, fallback)


def parse_optional_constraint_input(
    raw_value: object,
    default_value: Optional[int],
    minimum_value: int,
    field_label: str,
) -> Optional[int]:
    """Parse form/API constraint allowing numeric values or explicit no-constraint."""
    return parser_parse_optional_constraint_input(raw_value, default_value, minimum_value, field_label)


def parse_per_bus_capacities(raw_value: object) -> Dict[int, int]:
    """Parse optional per-bus capacity text like `1:40,2:52`."""
    return parser_parse_per_bus_capacities(raw_value)


def format_constraint_for_display(value: Optional[int], unit_label: str) -> str:
    """Render Optional[int] constraints as user-friendly text."""
    return parser_format_constraint_for_display(value, unit_label)


def ensure_fleet_csv_exists() -> None:
    """Ensure fleet CSV exists with the required schema."""
    FLEET_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not FLEET_CSV_PATH.exists():
        pd.DataFrame(columns=FLEET_COLUMNS).to_csv(FLEET_CSV_PATH, index=False)


def load_fleet_df() -> pd.DataFrame:
    """Load fleet CSV with required columns and normalized types."""
    ensure_fleet_csv_exists()
    try:
        fleet_df = pd.read_csv(FLEET_CSV_PATH)
    except Exception:
        fleet_df = pd.DataFrame(columns=FLEET_COLUMNS)

    for column in FLEET_COLUMNS:
        if column not in fleet_df.columns:
            fleet_df[column] = ""

    fleet_df = fleet_df[FLEET_COLUMNS].copy()
    fleet_df["bus_number"] = pd.to_numeric(fleet_df["bus_number"], errors="coerce")
    fleet_df["seating_capacity"] = pd.to_numeric(fleet_df["seating_capacity"], errors="coerce")
    fleet_df = fleet_df.dropna(subset=["bus_number"]).copy()
    fleet_df["bus_number"] = fleet_df["bus_number"].astype(int)
    fleet_df["seating_capacity"] = fleet_df["seating_capacity"].fillna(0).astype(int)
    fleet_df = fleet_df.sort_values("bus_number").drop_duplicates(subset=["bus_number"], keep="first")
    fleet_df = fleet_df.reset_index(drop=True)
    return fleet_df


def save_fleet_df(fleet_df: pd.DataFrame) -> None:
    """Write fleet dataframe to CSV with stable schema."""
    for column in FLEET_COLUMNS:
        if column not in fleet_df.columns:
            fleet_df[column] = ""
    fleet_df[FLEET_COLUMNS].to_csv(FLEET_CSV_PATH, index=False)


def parse_iso_date(date_text: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD date safely."""
    text = str(date_text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def renewal_status_from_date(due_date: Optional[datetime], today: datetime) -> Tuple[str, Optional[int]]:
    """Return renewal color status and days remaining for due date."""
    if due_date is None:
        return "unknown", None
    days_remaining = (due_date.date() - today.date()).days
    if days_remaining < 0:
        return "red", days_remaining
    if days_remaining <= 30:
        return "yellow", days_remaining
    return "green", days_remaining


def build_fleet_dashboard(fleet_df: pd.DataFrame, filter_key: str) -> Dict:
    """Build fleet rows with renewal diagnostics and summary counts."""
    today = datetime.now()
    rows: List[Dict] = []
    summary = {
        "total_buses": int(len(fleet_df)),
        "expiring_insurance": 0,
        "expiring_fc": 0,
        "expiring_tax": 0,
        "service_due_soon": 0,
    }

    for _, row in fleet_df.iterrows():
        insurance_status, insurance_days = renewal_status_from_date(
            parse_iso_date(row.get("insurance_expiry", "")), today
        )
        fc_status, fc_days = renewal_status_from_date(parse_iso_date(row.get("fc_expiry", "")), today)
        tax_status, tax_days = renewal_status_from_date(parse_iso_date(row.get("tax_expiry", "")), today)
        service_status, service_days = renewal_status_from_date(
            parse_iso_date(row.get("next_service_due", "")), today
        )

        if insurance_status in {"yellow", "red"}:
            summary["expiring_insurance"] += 1
        if fc_status in {"yellow", "red"}:
            summary["expiring_fc"] += 1
        if tax_status in {"yellow", "red"}:
            summary["expiring_tax"] += 1
        if service_status in {"yellow", "red"}:
            summary["service_due_soon"] += 1

        row_health = "healthy"
        if "red" in {insurance_status, fc_status, tax_status, service_status}:
            row_health = "expired"
        elif "yellow" in {insurance_status, fc_status, tax_status, service_status}:
            row_health = "expiring"

        rows.append(
            {
                "bus_number": int(row["bus_number"]),
                "registration_number": str(row.get("registration_number", "")),
                "seating_capacity": int(row.get("seating_capacity", 0)),
                "last_service_date": str(row.get("last_service_date", "")),
                "next_service_due": str(row.get("next_service_due", "")),
                "insurance_last_renewed": str(row.get("insurance_last_renewed", "")),
                "insurance_expiry": str(row.get("insurance_expiry", "")),
                "fc_last_done": str(row.get("fc_last_done", "")),
                "fc_expiry": str(row.get("fc_expiry", "")),
                "tax_last_paid": str(row.get("tax_last_paid", "")),
                "tax_expiry": str(row.get("tax_expiry", "")),
                "notes": str(row.get("notes", "")),
                "status": row_health,
                "insurance_status": insurance_status,
                "insurance_days": insurance_days,
                "fc_status": fc_status,
                "fc_days": fc_days,
                "tax_status": tax_status,
                "tax_days": tax_days,
                "service_status": service_status,
                "service_days": service_days,
            }
        )

    if filter_key == "expiring":
        rows = [row for row in rows if row["status"] == "expiring"]
    elif filter_key == "expired":
        rows = [row for row in rows if row["status"] == "expired"]
    elif filter_key == "healthy":
        rows = [row for row in rows if row["status"] == "healthy"]

    return {"rows": rows, "summary": summary}


def fleet_bus_numbers(requested_buses: int) -> List[int]:
    """Return bus numbers sourced from fleet CSV when available."""
    fleet_df = load_fleet_df()
    numbers = fleet_df["bus_number"].tolist()
    if len(numbers) >= requested_buses and requested_buses > 0:
        return numbers[:requested_buses]
    return [index + 1 for index in range(max(0, requested_buses))]



def fleet_capacity_for_bus(bus_number: int) -> int:
    """Return configured seating capacity for a bus number from fleet CSV, else 0."""
    fleet_df = load_fleet_df()
    match = fleet_df.loc[fleet_df["bus_number"] == int(bus_number), "seating_capacity"]
    if match.empty:
        return 0
    try:
        return max(0, int(match.iloc[0]))
    except Exception:
        return 0

def build_capacity_profile(
    bus_capacity: int,
    occupancy_percent: int,
    overflow_enabled: bool,
    overflow_limit: int,
) -> Dict[str, int | bool]:
    """Build planned/overflow/effective capacity figures for allocation."""
    safe_bus_capacity = max(1, int(bus_capacity))
    safe_occupancy_percent = max(1, int(occupancy_percent))
    planned_capacity = max(1, int(math.floor(safe_bus_capacity * (safe_occupancy_percent / 100.0))))
    overflow_capacity = max(0, int(overflow_limit)) if overflow_enabled else 0
    usable_capacity = planned_capacity + overflow_capacity
    return {
        "bus_capacity": safe_bus_capacity,
        "occupancy_percent": safe_occupancy_percent,
        "overflow_enabled": bool(overflow_enabled),
        "overflow_limit": max(0, int(overflow_limit)),
        "planned_capacity": planned_capacity,
        "overflow_capacity": overflow_capacity,
        "usable_capacity": max(1, usable_capacity),
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Fallback geodesic distance in kilometers between two coordinates."""
    radius_km = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def fallback_duration_seconds(distance_km: float) -> float:
    """Estimate travel time from distance when OSRM is unavailable."""
    if FALLBACK_AVERAGE_SPEED_KMH <= 0:
        return 0.0
    return (distance_km / FALLBACK_AVERAGE_SPEED_KMH) * 3600


def apply_traffic_inflation(travel_seconds: float) -> float:
    """Inflate road time to better reflect Chennai morning traffic conditions."""
    return float(travel_seconds) * MORNING_TRAFFIC_MULTIPLIER


def build_osrm_coord_string(points: List[Dict]) -> str:
    """Build semicolon-separated OSRM coordinate string in lon,lat order."""
    return ";".join(f"{p['lon']},{p['lat']}" for p in points)


def get_fallback_od_matrix(origins: List[Dict], destinations: List[Dict]) -> List[List[Dict]]:
    """Build fallback OD matrix using Haversine for all pairs."""
    matrix: List[List[Dict]] = []
    for origin in origins:
        row: List[Dict] = []
        oa = (float(origin["lat"]), float(origin["lon"]))
        for destination in destinations:
            db = (float(destination["lat"]), float(destination["lon"]))
            distance_km = haversine_km(oa[0], oa[1], db[0], db[1])
            row.append(
                {
                    "travel_seconds": apply_traffic_inflation(
                        fallback_duration_seconds(distance_km)
                    ),
                    "distance_km": distance_km,
                    "source": "haversine",
                }
            )
        matrix.append(row)
    return matrix


def osrm_get_json(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Call OSRM with timeout/retries/rate limiting. Returns None on final failure."""
    global _osrm_down_until
    down_until_ref = {"value": float(_osrm_down_until)}
    payload = service_osrm_get_json(
        path,
        params,
        osrm_base_url=OSRM_BASE_URL,
        timeout_seconds=OSRM_TIMEOUT_SECONDS,
        max_retries=OSRM_MAX_RETRIES,
        call_delay_seconds=OSRM_CALL_DELAY_SECONDS,
        cooldown_seconds=OSRM_COOLDOWN_SECONDS,
        down_until_ref=down_until_ref,
    )
    _osrm_down_until = float(down_until_ref["value"])
    return payload


def get_osrm_table_block(
    origins: List[Dict],
    destinations: List[Dict],
) -> Optional[List[List[Dict]]]:
    """Fetch one OD matrix block from OSRM /table; return None on failure."""
    return service_get_osrm_table_block(
        origins,
        destinations,
        table_batch_size=OSRM_TABLE_BATCH_SIZE,
        osrm_json_getter=lambda path, params=None: osrm_get_json(path, params=params),
        traffic_inflator=apply_traffic_inflation,
    )


def get_osrm_table_matrix(origins: List[Dict], destinations: List[Dict]) -> Optional[List[List[Dict]]]:
    """Fetch an OD matrix from OSRM /table using batched requests for larger inputs."""
    return service_get_osrm_table_matrix(
        origins,
        destinations,
        table_batch_size=OSRM_TABLE_BATCH_SIZE,
        get_table_block=get_osrm_table_block,
    )


def normalize_student_column_name(column_name: str) -> str:
    """Normalize CSV headers before alias matching."""
    return preprocessing_normalize_student_column_name(column_name)


def get_student_column_mapping(df: pd.DataFrame) -> Tuple[Dict[str, str], List[str]]:
    """Resolve uploaded CSV columns to canonical student field names."""
    return preprocessing_get_student_column_mapping(df, STUDENT_COLUMN_ALIASES)


def parse_student_csv(file_obj, source_filename: str) -> Tuple[pd.DataFrame, int]:
    """Load one student CSV, normalize schema, and return valid rows plus invalid count."""
    return preprocessing_parse_student_csv(file_obj, source_filename, STUDENT_COLUMN_ALIASES)


def merge_uploaded_student_csvs(uploaded_files: List) -> Tuple[pd.DataFrame, Dict]:
    """Merge one or many uploaded student CSVs into a routing-ready dataframe."""
    return preprocessing_merge_uploaded_student_csvs(uploaded_files, STUDENT_COLUMN_ALIASES)


def parse_csv(file_obj) -> pd.DataFrame:
    """Backward-compatible single CSV loader used by older call sites/tests."""
    students_df, _ = merge_uploaded_student_csvs([file_obj])
    return students_df


def generate_candidate_stops_500m(students_df: pd.DataFrame) -> pd.DataFrame:
    """Create candidate stops with roughly one stop per 500m catchment."""
    return preprocessing_generate_candidate_stops_500m(
        students_df,
        stop_spacing_km=STOP_SPACING_KM,
        haversine_km=haversine_km,
    )


def load_mtc_stops() -> pd.DataFrame:
    """Load local Chennai MTC stops from GTFS-style or OSM-export CSV headers."""
    return preprocessing_load_mtc_stops(MTC_STOPS_PATH)


def build_stops_for_source(
    students_df: pd.DataFrame,
    stop_source: str,
    warnings: List[str],
) -> Tuple[pd.DataFrame, str]:
    """Build stop candidates from the requested source, with safe fallback."""
    return preprocessing_build_stops_for_source(
        students_df,
        stop_source,
        warnings,
        mtc_stops_path=MTC_STOPS_PATH,
        stop_spacing_km=STOP_SPACING_KM,
        haversine_km=haversine_km,
    )


def get_travel_time_matrix_between(
    origins: List[Dict],
    destinations: List[Dict],
    warnings: List[str],
    context_label: str,
) -> Tuple[List[List[Dict]], str]:
    """Build an OD travel-time matrix via OSRM lookups with fallback-only-on-failure."""
    if not origins or not destinations:
        return [], "osrm"

    matrix = get_osrm_table_matrix(origins, destinations)
    if matrix is not None:
        return matrix, "osrm"

    warnings.append(
        f"OSRM unavailable/slow for {context_label}; using Haversine fallback for this run."
    )
    return get_fallback_od_matrix(origins, destinations), "haversine"


def get_travel_time_matrix(
    locations: List[Dict],
    warnings: List[str],
) -> Tuple[List[List[Dict]], str]:
    """Build an NxN travel-time and distance matrix for route optimization."""
    return get_travel_time_matrix_between(
        origins=locations,
        destinations=locations,
        warnings=warnings,
        context_label="route matrix",
    )


def assign_students_to_stops(
    students_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    warnings: List[str],
    cluster_centers: Optional[np.ndarray] = None,
    projection_meta: Optional[Dict[str, Dict]] = None,
) -> pd.DataFrame:
    """Assign each student to nearest stop, cluster-guided when centers are available."""
    if stops_df.empty:
        raise ValueError("No candidate stops available for assignment.")

    assigned_df = students_df.copy()
    stop_coords = np.radians(stops_df[["lat", "lon"]].to_numpy(dtype=float))
    global_tree = BallTree(stop_coords, metric="haversine")
    stop_ids = stops_df["stop_id"].astype(str).tolist()

    if cluster_centers is None or "cluster_id" not in assigned_df.columns:
        student_coords = np.radians(
            assigned_df[["latitude", "longitude"]].to_numpy(dtype=float)
        )
        _, nearest_indices = global_tree.query(student_coords, k=1)
        assigned_df["stop_id"] = [stop_ids[int(index)] for index in nearest_indices.flatten()]
        if projection_meta:
            assigned_df["stop_id"] = assigned_df["stop_id"].map(
                lambda sid: projection_meta.get(str(sid), {}).get("effective_stop_id", sid)
            )
        return assigned_df

    centers_rad = np.radians(np.asarray(cluster_centers, dtype=float))
    stop_cluster_tree = BallTree(centers_rad, metric="haversine")
    _, stop_cluster_idx = stop_cluster_tree.query(stop_coords, k=1)
    stops_with_cluster = stops_df.copy()
    stops_with_cluster["cluster_id"] = stop_cluster_idx.flatten().astype(int)

    assigned_df["stop_id"] = ""
    for cluster_id, cluster_students in assigned_df.groupby("cluster_id"):
        cluster_students_idx = cluster_students.index
        cluster_stop_rows = stops_with_cluster[stops_with_cluster["cluster_id"] == int(cluster_id)]

        if cluster_stop_rows.empty:
            coords = np.radians(cluster_students[["latitude", "longitude"]].to_numpy(dtype=float))
            _, nearest_indices = global_tree.query(coords, k=1)
            assigned_df.loc[cluster_students_idx, "stop_id"] = [
                stop_ids[int(index)] for index in nearest_indices.flatten()
            ]
            continue

        cluster_stop_coords = np.radians(cluster_stop_rows[["lat", "lon"]].to_numpy(dtype=float))
        cluster_tree = BallTree(cluster_stop_coords, metric="haversine")
        coords = np.radians(cluster_students[["latitude", "longitude"]].to_numpy(dtype=float))
        _, nearest_indices = cluster_tree.query(coords, k=1)
        cluster_stop_ids = cluster_stop_rows["stop_id"].astype(str).tolist()
        assigned_df.loc[cluster_students_idx, "stop_id"] = [
            cluster_stop_ids[int(index)] for index in nearest_indices.flatten()
        ]

    if projection_meta:
        assigned_df["stop_id"] = assigned_df["stop_id"].map(
            lambda sid: projection_meta.get(str(sid), {}).get("effective_stop_id", sid)
        )
    return assigned_df


def cluster_students_geographically(
    students_df: pd.DataFrame,
    n_clusters: int,
    warnings: List[str],
) -> Tuple[pd.DataFrame, Optional[np.ndarray]]:
    """Create geographic clusters for students to guide bus service zones."""
    clustered_df = students_df.copy()
    if n_clusters <= 1:
        clustered_df["cluster_id"] = 0
        return clustered_df, None

    if len(clustered_df) < n_clusters:
        n_clusters = len(clustered_df)
    if n_clusters <= 1:
        clustered_df["cluster_id"] = 0
        return clustered_df, None

    try:
        kmeans = MiniBatchKMeans(
            n_clusters=n_clusters,
            random_state=42,
            n_init="auto",
            batch_size=min(2048, len(clustered_df)),
        )
        coords = clustered_df[["latitude", "longitude"]].to_numpy(dtype=float)
        labels = kmeans.fit_predict(coords)
        clustered_df["cluster_id"] = labels.astype(int)
        return clustered_df, np.asarray(kmeans.cluster_centers_, dtype=float)
    except Exception:
        warnings.append("Geographic clustering failed; using global nearest-stop assignment.")
        clustered_df["cluster_id"] = 0
        return clustered_df, None


def assign_stop_corridors(
    stops_df: pd.DataFrame,
    corridor_count: int,
) -> pd.DataFrame:
    """Assign deterministic directional corridor ids for each stop."""
    stops = stops_df.copy()
    if stops.empty:
        stops["corridor"] = ""
        return stops

    corridor_count = max(CORRIDOR_SECTOR_MIN, min(CORRIDOR_SECTOR_MAX, int(corridor_count)))
    dx = stops["lon"].astype(float) - float(COLLEGE_LON)
    dy = stops["lat"].astype(float) - float(COLLEGE_LAT)
    angles = np.arctan2(dy.to_numpy(dtype=float), dx.to_numpy(dtype=float))
    normalized = ((angles + math.pi) / (2.0 * math.pi)) % 1.0
    sectors = np.floor(normalized * corridor_count).astype(int)
    sectors = np.clip(sectors, 0, corridor_count - 1)
    stops["corridor"] = [f"C{int(sector) + 1}" for sector in sectors]
    return stops


def classify_stop_accessibility(
    students_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    stop_source: str,
    routing_profile: Optional[Dict[str, object]] = None,
) -> pd.DataFrame:
    """Classify stop road suitability via lightweight deterministic heuristics."""
    stops = stops_df.copy()
    if stops.empty:
        stops["road_class"] = ""
        stops["accessibility_type"] = "accessible"
        stops["bus_accessible"] = True
        stops["dead_end_risk"] = 0.0
        stops["road_suitability_score"] = 1.0
        return stops

    student_coords = students_df[["latitude", "longitude"]].to_numpy(dtype=float)
    stop_coords = stops[["lat", "lon"]].to_numpy(dtype=float)
    near_radius_km = max(0.05, BUS_ACCESS_NEAR_SUPPORT_M / 1000.0)
    wide_radius_km = max(near_radius_km, BUS_ACCESS_WIDE_SUPPORT_M / 1000.0)

    near_counts: List[int] = []
    wide_counts: List[int] = []
    nearest_stop_km: List[float] = []

    for i, (slat, slon) in enumerate(stop_coords):
        d_to_students = np.array(
            [haversine_km(float(slat), float(slon), float(clat), float(clon)) for clat, clon in student_coords],
            dtype=float,
        )
        near_counts.append(int(np.sum(d_to_students <= near_radius_km)))
        wide_counts.append(int(np.sum(d_to_students <= wide_radius_km)))

        d_to_stops = np.array(
            [
                haversine_km(float(slat), float(slon), float(olat), float(olon))
                for j, (olat, olon) in enumerate(stop_coords) if j != i
            ],
            dtype=float,
        )
        nearest_stop_km.append(float(np.min(d_to_stops)) if d_to_stops.size else 9.9)

    road_class: List[str] = []
    accessibility_type: List[str] = []
    bus_accessible: List[bool] = []
    dead_end_risk: List[float] = []
    road_suitability_score: List[float] = []

    for row_idx, (near_support, wide_support, nearest_km) in enumerate(zip(near_counts, wide_counts, nearest_stop_km)):
        source_type = str(stops.iloc[row_idx].get("stop_source_type", stop_source or "generated")).strip().lower()
        verified_access = bool(stops.iloc[row_idx].get("accessibility_verified", False))
        if source_type == "mtc" or verified_access:
            cls = "secondary"
            risk = 0.0
            is_accessible = True
            road_class.append(cls)
            dead_end_risk.append(float(risk))
            bus_accessible.append(is_accessible)
            accessibility_type.append("verified_transit")
            road_suitability_score.append(1.0)
            continue

        if source_type == "mtc":
            if nearest_km > 0.9 and near_support <= 2:
                cls = "residential"
            elif wide_support >= 20:
                cls = "primary"
            elif wide_support >= 12:
                cls = "secondary"
            else:
                cls = "tertiary"
        else:
            if near_support <= 2 and wide_support <= 4 and nearest_km > 0.28:
                cls = "service/internal"
            elif near_support <= 3 and wide_support <= 7:
                cls = "residential"
            elif wide_support <= 12:
                cls = "tertiary"
            elif wide_support <= 20:
                cls = "secondary"
            else:
                cls = "primary"

        risk = 0.0
        if cls == "service/internal":
            risk = 0.95 if nearest_km > 0.35 else 0.8
        elif cls == "residential":
            risk = 0.65 if nearest_km > 0.35 else 0.45
        elif cls == "tertiary":
            risk = 0.2

        road_class.append(cls)
        dead_end_risk.append(float(risk))
        profile = routing_profile or routing_policy_profile(DEFAULT_ROUTING_POLICY)
        allow_residential = bool(profile.get("allow_residential", True))
        allow_internal = bool(profile.get("allow_internal", False))
        is_accessible = cls in {"primary", "secondary", "tertiary"} or (allow_residential and cls == "residential" and risk < 0.75) or (allow_internal and cls == "service/internal" and risk < 0.9)
        bus_accessible.append(is_accessible)
        accessibility_type.append("accessible" if is_accessible else "inaccessible")
        road_suitability_score.append(float(max(0.05, min(1.0, 1.0 - risk))))

    stops["road_class"] = road_class
    stops["accessibility_type"] = accessibility_type
    stops["bus_accessible"] = bus_accessible
    stops["dead_end_risk"] = dead_end_risk
    stops["road_suitability_score"] = road_suitability_score
    return stops


def project_stops_to_accessible_roads(
    stops_df: pd.DataFrame,
    max_walk_km: Optional[float],
) -> Tuple[pd.DataFrame, Dict[str, Dict]]:
    """Project inaccessible stops to nearest accessible stops and consolidate."""
    stops = stops_df.copy()
    if stops.empty:
        return stops, {}

    for column in ("projected", "projected_to_stop_id", "projection_walk_km", "projected_from_count"):
        if column not in stops.columns:
            stops[column] = 0 if column == "projected_from_count" else (False if column == "projected" else "")
    stops["projection_walk_km"] = pd.to_numeric(stops["projection_walk_km"], errors="coerce").fillna(0.0)

    accessible = stops[stops["bus_accessible"] == True].copy()
    if accessible.empty:
        return stops, {}

    accessible_coords = np.radians(accessible[["lat", "lon"]].to_numpy(dtype=float))
    accessible_tree = BallTree(accessible_coords, metric="haversine")
    accessible_ids = accessible["stop_id"].astype(str).tolist()
    stop_id_to_index = {
        str(stop_id): int(idx)
        for idx, stop_id in zip(stops.index.tolist(), stops["stop_id"].astype(str).tolist())
    }

    projection_meta: Dict[str, Dict] = {}
    keep_mask = np.ones(len(stops), dtype=bool)

    for idx, row in stops.iterrows():
        stop_id = str(row["stop_id"])
        if bool(row.get("accessibility_verified", False)):
            projection_meta[stop_id] = {
                "effective_stop_id": stop_id,
                "projected": False,
                "projection_walk_km": 0.0,
                "walking_distance_m": 0.0,
            }
            continue
        if bool(row["bus_accessible"]):
            projection_meta[stop_id] = {
                "effective_stop_id": stop_id,
                "projected": False,
                "projection_walk_km": 0.0,
                "walking_distance_m": 0.0,
            }
            continue

        coords = np.radians([[float(row["lat"]), float(row["lon"])]])
        distances, nearest_idx = accessible_tree.query(coords, k=1)
        nearest_id = str(accessible_ids[int(nearest_idx[0][0])])
        walk_km = float(distances[0][0] * 6371.0)

        if (max_walk_km is None) or (walk_km <= float(max_walk_km)):
            projection_meta[stop_id] = {
                "effective_stop_id": nearest_id,
                "projected": True,
                "projection_walk_km": walk_km,
                "walking_distance_m": walk_km * 1000.0,
            }
            keep_mask[idx] = False
            anchor = stop_id_to_index.get(nearest_id)
            if anchor is not None:
                stops.at[anchor, "projected_from_count"] = int(stops.at[anchor, "projected_from_count"]) + 1
        else:
            projection_meta[stop_id] = {
                "effective_stop_id": stop_id,
                "projected": False,
                "projection_walk_km": walk_km,
                "walking_distance_m": walk_km * 1000.0,
                "projection_rejected": True,
            }

    consolidated = stops.loc[keep_mask].copy().reset_index(drop=True)
    consolidated["projected"] = consolidated["projected_from_count"].astype(int) > 0
    consolidated["projected_stop"] = consolidated["projected"]
    consolidated["projection_walk_km"] = 0.0
    consolidated["walking_distance_m"] = 0.0

    # Carry the shortest projection walk distance into anchor rows for diagnostics.
    best_walk_by_anchor: Dict[str, float] = {}
    for original_id, meta in projection_meta.items():
        target = str(meta.get("effective_stop_id", original_id))
        walk_km = float(meta.get("projection_walk_km", 0.0))
        if not bool(meta.get("projected", False)):
            continue
        if target not in best_walk_by_anchor or walk_km < best_walk_by_anchor[target]:
            best_walk_by_anchor[target] = walk_km

    for idx, row in consolidated.iterrows():
        sid = str(row["stop_id"])
        consolidated.at[idx, "projection_walk_km"] = float(best_walk_by_anchor.get(sid, 0.0))
        consolidated.at[idx, "walking_distance_m"] = float(best_walk_by_anchor.get(sid, 0.0) * 1000.0)
        consolidated.at[idx, "projected_to_stop_id"] = sid if bool(row["projected"]) else ""
        if bool(row["projected"]):
            consolidated.at[idx, "accessibility_type"] = "projected_accessible"
            consolidated.at[idx, "stop_source_type"] = "projected"

    return consolidated, projection_meta


def build_bus_accessible_stops(
    students_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    stop_source: str,
    warnings: List[str],
    routing_policy_name: str = DEFAULT_ROUTING_POLICY,
) -> Tuple[pd.DataFrame, Dict[str, Dict]]:
    """Apply accessibility classification + projection + consolidation."""
    profile = routing_policy_profile(routing_policy_name)
    classified = classify_stop_accessibility(students_df, stops_df, stop_source=stop_source, routing_profile=profile)
    default_walk_km = max(0.05, min(BUS_ACCESS_MAX_WALK_M / 1000.0, max(BUS_ACCESS_MAX_WALK_KM, BUS_ACCESS_MIN_WALK_M / 1000.0)))
    projected, projection_meta = project_stops_to_accessible_roads(
        classified,
        max_walk_km=profile.get("max_walk_km", default_walk_km),
    )

    total_inaccessible = int((classified["bus_accessible"] == False).sum())
    projected_count = sum(1 for _, meta in projection_meta.items() if bool(meta.get("projected", False)))
    rejected_count = sum(1 for _, meta in projection_meta.items() if bool(meta.get("projection_rejected", False)))
    consolidated_count = int(projected["projected_from_count"].sum()) if "projected_from_count" in projected.columns else 0

    if total_inaccessible > 0:
        warnings.append(
            f"{total_inaccessible} narrow/internal stops detected; {projected_count} projected to bus-accessible pickups."
        )
    if rejected_count > 0:
        warnings.append(
            f"{rejected_count} inaccessible stops exceeded walk-radius threshold and were kept as-is."
        )
    if consolidated_count > 0:
        warnings.append(
            f"Shared pickup consolidation merged {consolidated_count} projected lane stops."
        )

    return projected, projection_meta


def build_stop_chunks(
    assigned_students_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    target_bus_load: int,
) -> List[Dict]:
    """Build stop demand chunks; later allocation may split them across buses."""
    stop_lookup = {
        str(row["stop_id"]): {
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "stop_name": str(row["stop_name"]),
            "corridor": str(row.get("corridor", "")),
            "road_class": str(row.get("road_class", "tertiary")),
            "stop_source_type": str(row.get("stop_source_type", "generated")),
            "accessibility_verified": bool(row.get("accessibility_verified", False)),
            "accessibility_type": str(row.get("accessibility_type", "accessible")),
            "dead_end_risk": float(row.get("dead_end_risk", 0.0)),
            "road_suitability_score": float(row.get("road_suitability_score", 0.7)),
            "projected": bool(row.get("projected", False)),
            "projected_stop": bool(row.get("projected_stop", row.get("projected", False))),
            "projection_walk_km": float(row.get("projection_walk_km", 0.0)),
            "walking_distance_m": float(row.get("walking_distance_m", 0.0)),
            "original_stop_id": str(row.get("original_stop_id", row.get("stop_id", ""))),
            "original_lat": float(row.get("original_lat", row.get("lat", 0.0))),
            "original_lon": float(row.get("original_lon", row.get("lon", 0.0))),
        }
        for _, row in stops_df.iterrows()
    }

    chunks: List[Dict] = []
    grouped = assigned_students_df.groupby("stop_id")

    for stop_id, group in grouped:
        stop_key = str(stop_id)
        student_indices = group.index.tolist()
        cluster_id = (
            int(group["cluster_id"].mode().iloc[0])
            if "cluster_id" in group.columns and not group["cluster_id"].isna().all()
            else None
        )
        chunks.append(
            {
                "stop_id": stop_key,
                "base_stop_id": stop_key,
                "stop_name": stop_lookup[stop_key]["stop_name"],
                "lat": stop_lookup[stop_key]["lat"],
                "lon": stop_lookup[stop_key]["lon"],
                "student_indices": student_indices,
                "student_count": int(len(student_indices)),
                "cluster_id": cluster_id,
                "corridor": stop_lookup[stop_key]["corridor"],
                "road_class": stop_lookup[stop_key]["road_class"],
                "stop_source_type": stop_lookup[stop_key]["stop_source_type"],
                "accessibility_verified": stop_lookup[stop_key]["accessibility_verified"],
                "accessibility_type": stop_lookup[stop_key]["accessibility_type"],
                "dead_end_risk": stop_lookup[stop_key]["dead_end_risk"],
                "road_suitability_score": stop_lookup[stop_key]["road_suitability_score"],
                "projected": stop_lookup[stop_key]["projected"],
                "projected_stop": stop_lookup[stop_key]["projected_stop"],
                "projection_walk_km": stop_lookup[stop_key]["projection_walk_km"],
                "walking_distance_m": stop_lookup[stop_key]["walking_distance_m"],
                "original_stop_id": stop_lookup[stop_key]["original_stop_id"],
                "original_lat": stop_lookup[stop_key]["original_lat"],
                "original_lon": stop_lookup[stop_key]["original_lon"],
            }
        )

    chunks.sort(key=lambda c: c["student_count"], reverse=True)
    return chunks


def corridor_alignment_score(stop_corridor: str, bus_corridor_counts: Dict[str, int]) -> float:
    """Return [0..1] corridor alignment score based on bus serving history."""
    return routing_corridor_alignment_score(stop_corridor, bus_corridor_counts)


def allocate_chunks_to_buses(
    chunks: List[Dict],
    requested_buses: int,
    target_bus_load: int,
    preferred_bus_numbers: Optional[List[int]] = None,
    cluster_bus_numbers: Optional[Dict[int, int]] = None,
    bus_usable_capacity_by_number: Optional[Dict[int, int]] = None,
    bus_actual_capacity_by_number: Optional[Dict[int, int]] = None,
    default_actual_capacity: Optional[int] = None,
    routing_policy_name: str = DEFAULT_ROUTING_POLICY,
) -> Tuple[List[Dict], Dict[int, Dict[str, str | int]]]:
    """Corridor-aware adaptive allocation with partial stop splitting."""
    initial_numbers = preferred_bus_numbers or [i + 1 for i in range(requested_buses)]
    buses = [
        {
            "bus_number": int(initial_numbers[i]),
            "capacity": int(
                (bus_usable_capacity_by_number or {}).get(int(initial_numbers[i]), target_bus_load)
            ),
            "remaining_capacity": int(
                (bus_usable_capacity_by_number or {}).get(int(initial_numbers[i]), target_bus_load)
            ),
            "actual_capacity": int(
                (bus_actual_capacity_by_number or {}).get(
                    int(initial_numbers[i]),
                    default_actual_capacity if default_actual_capacity is not None else target_bus_load,
                )
            ),
            "chunks": [],
            "primary_corridor": "",
            "served_corridors": [],
        }
        for i in range(len(initial_numbers))
    ]
    next_bus_number = (max(initial_numbers) + 1) if initial_numbers else 1
    bus_states: Dict[int, Dict] = {
        int(bus["bus_number"]): {
            "corridor_counts": {},
            "assigned_stops": [],
            "farthest_km": 0.0,
            "cluster_seed": None,
        }
        for bus in buses
    }
    stop_split_counters: Dict[str, int] = {}
    student_assignment_map: Dict[int, Dict[str, str | int]] = {}
    routing_profile = routing_policy_profile(routing_policy_name)
    road_penalty_by_class = dict(routing_profile.get("road_penalties", {}))

    def bus_centroid(bus_obj: Dict) -> Tuple[float, float]:
        if not bus_obj["chunks"]:
            return float(COLLEGE_LAT), float(COLLEGE_LON)
        lat = float(np.mean([float(c["lat"]) for c in bus_obj["chunks"]]))
        lon = float(np.mean([float(c["lon"]) for c in bus_obj["chunks"]]))
        return lat, lon

    def evaluate_assignment_cost(bus_obj: Dict, state: Dict, stop_chunk: Dict) -> float:
        centroid_lat, centroid_lon = bus_centroid(bus_obj)
        stop_lat = float(stop_chunk["lat"])
        stop_lon = float(stop_chunk["lon"])
        distance_cost = haversine_km(centroid_lat, centroid_lon, stop_lat, stop_lon)
        campus_cost = haversine_km(stop_lat, stop_lon, COLLEGE_LAT, COLLEGE_LON)
        detour_cost = max(0.0, distance_cost - (0.45 * campus_cost))
        occupancy_penalty = (1.0 - (float(bus_obj["remaining_capacity"]) / max(1.0, float(bus_obj["capacity"])))) * 8.0
        projected_farthest = max(state["farthest_km"], campus_cost)
        route_stretch_penalty = max(0.0, projected_farthest - state["farthest_km"]) * 0.7
        corridor_bonus = corridor_alignment_score(str(stop_chunk.get("corridor", "")), state["corridor_counts"]) * 8.0
        direction_alignment_bonus = max(0.0, 1.0 - abs(centroid_lon - COLLEGE_LON)) * 1.5
        centroid_to_campus = haversine_km(centroid_lat, centroid_lon, COLLEGE_LAT, COLLEGE_LON)
        inward_progress_bonus = 1.8 if campus_cost <= centroid_to_campus + 0.45 else 0.0
        lateral_jump_penalty = max(0.0, distance_cost - max(0.25, abs(campus_cost - centroid_to_campus) + 0.25)) * 0.7
        road_class = str(stop_chunk.get("road_class", "tertiary"))
        bus_access_penalty = float(road_penalty_by_class.get(road_class, 1.0))
        dead_end_penalty = float(stop_chunk.get("dead_end_risk", 0.0)) * 2.8
        access_type = str(stop_chunk.get("accessibility_type", "accessible"))
        projected_bonus = 0.7 if access_type == "projected_accessible" else 0.0
        suitability_bonus = float(stop_chunk.get("road_suitability_score", 0.7)) * 1.2
        spillover_bonus = 0.0
        if bus_obj["chunks"] and distance_cost <= 2.2 and int(bus_obj["remaining_capacity"]) > 0:
            # Prefer nearby "on-the-way" absorption with spare capacity.
            spillover_bonus = min(2.0, (float(bus_obj["remaining_capacity"]) / max(1.0, float(bus_obj["capacity"]))) * 2.0)
        return (
            distance_cost
            + detour_cost
            + occupancy_penalty
            + route_stretch_penalty
            + lateral_jump_penalty
            + bus_access_penalty
            + dead_end_penalty
            - corridor_bonus
            - direction_alignment_bonus
            - inward_progress_bonus
            - projected_bonus
            - suitability_bonus
            - spillover_bonus
        )

    def violates_thresholds(bus_obj: Dict, state: Dict, stop_chunk: Dict) -> bool:
        if not bus_obj["chunks"]:
            return False
        centroid_lat, centroid_lon = bus_centroid(bus_obj)
        stop_lat = float(stop_chunk["lat"])
        stop_lon = float(stop_chunk["lon"])
        incremental_detour = haversine_km(centroid_lat, centroid_lon, stop_lat, stop_lon)
        if incremental_detour > ASSIGNMENT_MAX_DETOUR_KM:
            return True
        farthest_candidate = max(
            state["farthest_km"],
            haversine_km(stop_lat, stop_lon, COLLEGE_LAT, COLLEGE_LON),
        )
        baseline = max(0.5, state["farthest_km"])
        stretch_ratio = farthest_candidate / baseline
        if stretch_ratio > ASSIGNMENT_MAX_STRETCH_RATIO:
            return True
        if bool(routing_profile.get("hard_directional", True)):
            tolerance = float(routing_profile.get("outward_tolerance_km", 0.15))
            campus_cost = haversine_km(stop_lat, stop_lon, COLLEGE_LAT, COLLEGE_LON)
            if state["farthest_km"] > 0 and campus_cost > float(state["farthest_km"]) + tolerance:
                return True
        return False

    def refresh_bus_state(bus_obj: Dict) -> Dict:
        return routing_refresh_bus_state(
            bus_obj,
            bus_states,
            COLLEGE_LAT,
            COLLEGE_LON,
            haversine_km,
        )


    def lane_blocked(stop_chunk: Dict) -> bool:
        road_class = str(stop_chunk.get("road_class", "tertiary")).strip().lower()
        if road_class == "residential" and not bool(routing_profile.get("allow_residential", True)):
            return True
        if road_class == "service/internal" and not bool(routing_profile.get("allow_internal", False)):
            return True
        return False

    for chunk in chunks:
        remaining_students = list(chunk["student_indices"])
        base_stop_id = str(chunk["base_stop_id"])

        while remaining_students:
            def collect_candidates(allow_blocked_lanes: bool) -> List[Tuple[float, Dict]]:
                local_candidates: List[Tuple[float, Dict]] = []
                for bus in buses:
                    if bus["remaining_capacity"] <= 0:
                        continue
                    state = bus_states[int(bus["bus_number"])]
                    if violates_thresholds(bus, state, chunk):
                        continue
                    if (not allow_blocked_lanes) and lane_blocked(chunk):
                        continue
                    cost = evaluate_assignment_cost(bus, state, chunk)
                    chunk_cluster = chunk.get("cluster_id")
                    if cluster_bus_numbers is not None and chunk_cluster is not None:
                        preferred_bus_num = cluster_bus_numbers.get(int(chunk_cluster))
                        if preferred_bus_num == int(bus["bus_number"]):
                            cost -= 3.5
                    local_candidates.append((float(cost), bus))
                return local_candidates

            candidates = collect_candidates(allow_blocked_lanes=False)
            if not candidates:
                candidates = collect_candidates(allow_blocked_lanes=True)

            if not candidates:
                bus_number = next_bus_number
                next_bus_number += 1
                new_bus = {
                    "bus_number": bus_number,
                    "capacity": target_bus_load,
                    "remaining_capacity": target_bus_load,
                    "actual_capacity": int(default_actual_capacity if default_actual_capacity is not None else target_bus_load),
                    "chunks": [],
                    "primary_corridor": "",
                    "served_corridors": [],
                }
                buses.append(new_bus)
                bus_states[bus_number] = {
                    "corridor_counts": {},
                    "assigned_stops": [],
                    "farthest_km": 0.0,
                    "cluster_seed": chunk.get("cluster_id"),
                }
                candidates = [(0.0, new_bus)]

            _, selected_bus = min(
                candidates,
                key=lambda item: (item[0], int(item[1]["bus_number"])),
            )
            selected_state = bus_states[int(selected_bus["bus_number"])]
            take_count = min(int(selected_bus["remaining_capacity"]), len(remaining_students))
            assigned_slice = remaining_students[:take_count]
            remaining_students = remaining_students[take_count:]

            split_counter = stop_split_counters.get(base_stop_id, 0) + 1
            stop_split_counters[base_stop_id] = split_counter
            split_stop_id = f"{base_stop_id}__B{int(selected_bus['bus_number'])}_{split_counter}"
            chunk_payload = {
                "stop_id": split_stop_id,
                "base_stop_id": base_stop_id,
                "stop_name": str(chunk["stop_name"]),
                "lat": float(chunk["lat"]),
                "lon": float(chunk["lon"]),
                "student_count": int(take_count),
                "student_indices": assigned_slice,
                "cluster_id": chunk.get("cluster_id"),
                "corridor": str(chunk.get("corridor", "")),
                "road_class": str(chunk.get("road_class", "tertiary")),
                "accessibility_type": str(chunk.get("accessibility_type", "accessible")),
                "dead_end_risk": float(chunk.get("dead_end_risk", 0.0)),
                "road_suitability_score": float(chunk.get("road_suitability_score", 0.7)),
                "projected": bool(chunk.get("projected", False)),
                "projection_walk_km": float(chunk.get("projection_walk_km", 0.0)),
                "walking_distance_m": float(chunk.get("walking_distance_m", 0.0)),
            }
            selected_bus["chunks"].append(chunk_payload)
            selected_bus["remaining_capacity"] -= int(take_count)

            corridor_id = str(chunk.get("corridor", ""))
            if corridor_id:
                selected_state["corridor_counts"][corridor_id] = selected_state["corridor_counts"].get(corridor_id, 0) + int(take_count)
            selected_state["assigned_stops"].append(split_stop_id)
            selected_state["farthest_km"] = max(
                float(selected_state["farthest_km"]),
                haversine_km(float(chunk["lat"]), float(chunk["lon"]), COLLEGE_LAT, COLLEGE_LON),
            )

            for idx in assigned_slice:
                student_assignment_map[int(idx)] = {
                    "stop_id": split_stop_id,
                    "bus_number": int(selected_bus["bus_number"]),
                }

    # Local improvement pass: only move fully movable tail chunks when strongly better.
    for bus in list(buses):
        for tail_chunk in list(bus["chunks"]):
            current_bus_num = int(bus["bus_number"])
            current_state = bus_states[current_bus_num]
            current_cost = evaluate_assignment_cost(bus, current_state, tail_chunk)
            best_target = None
            best_delta = 0.0
            for candidate in buses:
                if int(candidate["bus_number"]) == current_bus_num:
                    continue
                if int(candidate["remaining_capacity"]) < int(tail_chunk["student_count"]):
                    continue
                candidate_state = bus_states[int(candidate["bus_number"])]
                if violates_thresholds(candidate, candidate_state, tail_chunk):
                    continue
                candidate_cost = evaluate_assignment_cost(candidate, candidate_state, tail_chunk)
                delta = current_cost - candidate_cost
                if delta > best_delta + 1.5:
                    best_delta = delta
                    best_target = candidate
            if best_target is None:
                continue
            bus["chunks"].remove(tail_chunk)
            bus["remaining_capacity"] += int(tail_chunk["student_count"])
            best_target["chunks"].append(tail_chunk)
            best_target["remaining_capacity"] -= int(tail_chunk["student_count"])
            refresh_bus_state(bus)
            refresh_bus_state(best_target)
            for student_idx in tail_chunk["student_indices"]:
                student_assignment_map[int(student_idx)] = {
                    "stop_id": str(tail_chunk["stop_id"]),
                    "bus_number": int(best_target["bus_number"]),
                }

    # Final corridor identity and consistency fields.
    for bus in buses:
        final_corridor_counts: Dict[str, int] = {}
        for chunk in bus["chunks"]:
            corridor_id = str(chunk.get("corridor", ""))
            if not corridor_id:
                continue
            final_corridor_counts[corridor_id] = final_corridor_counts.get(corridor_id, 0) + int(chunk["student_count"])
        if final_corridor_counts:
            primary = max(
                final_corridor_counts.items(),
                key=lambda item: (int(item[1]), str(item[0])),
            )[0]
        else:
            primary = ""
        bus["primary_corridor"] = primary
        bus["served_corridors"] = sorted(final_corridor_counts.keys())

    return [bus for bus in buses if bus["chunks"]], student_assignment_map


def nearest_neighbor_route_by_time(
    stop_ids: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
) -> List[str]:
    """Order stops by nearest-neighbor on driving time and end at college."""
    return routing_nearest_neighbor_route_by_time(stop_ids, matrix, index_map, college_id)


def optimize_stop_order_with_ortools(
    stop_ids: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
) -> List[str]:
    """Optimize stop sequence via OR-Tools; fallback to nearest-neighbor when unavailable."""
    return routing_optimize_stop_order_with_ortools(
        stop_ids,
        matrix,
        index_map,
        college_id,
        ortools_available=ORTOOLS_AVAILABLE,
        pywrapcp=pywrapcp if ORTOOLS_AVAILABLE else None,
        routing_enums_pb2=routing_enums_pb2 if ORTOOLS_AVAILABLE else None,
    )


def estimate_route_shape_cost(
    path: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
    location_by_id: Dict[str, Dict],
) -> float:
    """Directional shape-aware cost: travel + backtrack/lateral/reversal penalties."""
    return routing_estimate_route_shape_cost(
        path,
        matrix,
        index_map,
        college_id,
        location_by_id,
        haversine_km,
        COLLEGE_LAT,
        COLLEGE_LON,
    )


def refine_stop_order_directional(
    path: List[str],
    matrix: List[List[Dict]],
    index_map: Dict[str, int],
    college_id: str,
    location_by_id: Dict[str, Dict],
) -> List[str]:
    """Bounded deterministic 2-opt style smoothing for inward directional continuity."""
    return routing_refine_stop_order_directional(
        path,
        matrix,
        index_map,
        college_id,
        location_by_id,
        haversine_km,
        COLLEGE_LAT,
        COLLEGE_LON,
        ROUTE_SHAPE_2OPT_MAX_PASSES,
        ROUTE_SHAPE_2OPT_MAX_SWAPS,
    )


def get_osrm_route_geometry(route_points: List[Dict], warnings: List[str]) -> List[List[float]]:
    """Fetch road-following route geometry from OSRM route API."""
    if len(route_points) < 2:
        return [[float(p["lat"]), float(p["lon"])] for p in route_points]

    coord_string = build_osrm_coord_string(route_points)
    payload = osrm_get_json(
        f"/route/v1/driving/{coord_string}",
        params={"overview": "full", "geometries": "geojson"},
    )

    if not payload or payload.get("code") != "Ok":
        warnings.append("OSRM route geometry failed; straight-line fallback geometry used.")
        return [[float(p["lat"]), float(p["lon"])] for p in route_points]

    routes = payload.get("routes", [])
    if not routes:
        warnings.append("OSRM route geometry returned no routes; fallback geometry used.")
        return [[float(p["lat"]), float(p["lon"])] for p in route_points]

    coordinates = routes[0].get("geometry", {}).get("coordinates", [])
    if not coordinates:
        warnings.append("OSRM route geometry missing coordinates; fallback geometry used.")
        return [[float(p["lat"]), float(p["lon"])] for p in route_points]

    return [[float(lat), float(lon)] for lon, lat in coordinates]


def route_and_schedule_buses(
    buses: List[Dict],
    route_locations: List[Dict],
    route_matrix: List[List[Dict]],
    warnings: List[str],
    base_arrival_time: str,
    max_ride_duration_minutes: Optional[int],
    stop_dwell_seconds: Optional[int],
    routing_policy_name: str = DEFAULT_ROUTING_POLICY,
) -> Tuple[List[Dict], float, float, float]:
    """Compute route order, pickup schedule, and per-bus metrics."""
    try:
        base_arrival = datetime.strptime(str(base_arrival_time), "%H:%M")
    except ValueError:
        base_arrival = datetime.strptime(BASE_ARRIVAL_TIME, "%H:%M")
    location_by_id = {loc["id"]: loc for loc in route_locations}
    index_map = {loc["id"]: idx for idx, loc in enumerate(route_locations)}
    college_id = "COLLEGE"
    routing_profile = routing_policy_profile(routing_policy_name)

    routed_buses: List[Dict] = []
    total_distance_km = 0.0
    total_duration_minutes = 0.0

    def corridor_time_multiplier(corridor_id: str, hhmm: str) -> float:
        hour = 8
        try:
            hour = int(str(hhmm).split(":")[0])
        except Exception:
            hour = 8
        if 7 <= hour < 8:
            base = 1.08
        elif 8 <= hour < 9:
            base = 1.14
        else:
            base = 1.0
        if corridor_id.endswith(("1", "2")):
            base += 0.04
        return float(base)

    def road_type_multiplier(road_class: str) -> float:
        mapping = {
            "primary": 1.0,
            "secondary": 1.03,
            "tertiary": 1.06,
            "residential": 1.0,
            "service/internal": 1.14,
        }
        return float(mapping.get(str(road_class), 1.05))

    for bus_index, bus in enumerate(buses, start=1):
        students_per_stop: Dict[str, int] = {}
        for chunk in bus["chunks"]:
            students_per_stop[chunk["stop_id"]] = (
                students_per_stop.get(chunk["stop_id"], 0) + chunk["student_count"]
            )

        stop_ids = list(students_per_stop.keys())
        pickup_order_ids = optimize_stop_order_with_ortools(
            stop_ids=stop_ids,
            matrix=route_matrix,
            index_map=index_map,
            college_id=college_id,
        )
        pickup_order_ids = refine_stop_order_directional(
            path=pickup_order_ids,
            matrix=route_matrix,
            index_map=index_map,
            college_id=college_id,
            location_by_id=location_by_id,
        )
        if bool(routing_profile.get("hard_directional", True)):
            pickup_order_ids = sorted(
                pickup_order_ids,
                key=lambda sid: haversine_km(
                    float(location_by_id[sid]["lat"]),
                    float(location_by_id[sid]["lon"]),
                    COLLEGE_LAT,
                    COLLEGE_LON,
                ),
                reverse=True,
            )

        route_order = pickup_order_ids + [college_id]

        route_distance_km = 0.0
        route_duration_seconds = 0.0
        leg_seconds: List[float] = []
        boarding_seconds_per_stop: List[float] = []

        for i in range(len(route_order) - 1):
            src_id = route_order[i]
            dst_id = route_order[i + 1]
            metric = route_matrix[index_map[src_id]][index_map[dst_id]]
            src_info = location_by_id.get(src_id, {})
            corridor_mult = corridor_time_multiplier(str(src_info.get("corridor", "")), base_arrival_time)
            road_mult = road_type_multiplier(str(src_info.get("road_class", "tertiary")))
            leg_time = float(metric["travel_seconds"]) * corridor_mult * road_mult
            leg_distance = float(metric["distance_km"])
            leg_seconds.append(leg_time)

            route_distance_km += leg_distance
            route_duration_seconds += leg_time

        arrival_time = base_arrival + timedelta(minutes=(bus_index - 1) * ARRIVAL_STAGGER_MINUTES)

        pickup_times: Dict[str, str] = {}
        boarding_time_strings: Dict[str, str] = {}
        stop_boarding_seconds: Dict[str, float] = {}
        effective_stop_dwell_seconds = 0 if stop_dwell_seconds is None else max(0, int(stop_dwell_seconds))
        for stop_id in pickup_order_ids:
            boarding_seconds = students_per_stop.get(stop_id, 0) * BOARDING_SECONDS_PER_STUDENT
            boarding_seconds += effective_stop_dwell_seconds
            stop_boarding_seconds[stop_id] = float(boarding_seconds)
            boarding_time_strings[stop_id] = f"{int(boarding_seconds // 60)}m {int(boarding_seconds % 60)}s"
            boarding_seconds_per_stop.append(float(boarding_seconds))

        route_duration_seconds += sum(boarding_seconds_per_stop)

        for idx, stop_id in enumerate(pickup_order_ids):
            remaining_drive_seconds = sum(leg_seconds[idx:])
            remaining_boarding_seconds = sum(
                stop_boarding_seconds[remaining_stop_id]
                for remaining_stop_id in pickup_order_ids[idx:]
            )
            seconds_from_stop_to_arrival = (
                remaining_drive_seconds + remaining_boarding_seconds
            )
            pickup_time = arrival_time - timedelta(seconds=seconds_from_stop_to_arrival)
            pickup_times[stop_id] = pickup_time.strftime("%H:%M")

        map_stops = []
        ordered_stops = []
        for stop_number, stop_id in enumerate(pickup_order_ids, start=1):
            stop_info = location_by_id[stop_id]
            students_count = int(students_per_stop.get(stop_id, 0))

            stop_payload = {
                "stop_number": stop_number,
                "stop_id": stop_id,
                "name": stop_info["name"],
                "lat": stop_info["lat"],
                "lon": stop_info["lon"],
                "corridor": str(stop_info.get("corridor", "")),
                "road_class": str(stop_info.get("road_class", "tertiary")),
                "accessibility_type": str(stop_info.get("accessibility_type", "accessible")),
                "projected_stop": bool(stop_info.get("projected", False)),
                "walking_distance_m": float(stop_info.get("walking_distance_m", 0.0)),
                "road_suitability_score": float(stop_info.get("road_suitability_score", 0.7)),
                "base_stop_id": str(stop_info.get("base_stop_id", stop_id)),
                "students_count": students_count,
                "pickup_time": pickup_times[stop_id],
                "pickup_window": format_pickup_window(pickup_times[stop_id]),
                "boarding_time": boarding_time_strings[stop_id],
            }
            map_stops.append(stop_payload)
            ordered_stops.append(stop_payload)

        route_points = [
            {
                "id": sid,
                "name": location_by_id[sid]["name"],
                "lat": location_by_id[sid]["lat"],
                "lon": location_by_id[sid]["lon"],
            }
            for sid in route_order
        ]

        route_geometry = get_osrm_route_geometry(route_points, warnings)

        total_students = int(sum(chunk["student_count"] for chunk in bus["chunks"]))
        route_duration_minutes = route_duration_seconds / 60.0
        ride_duration_warning = (
            max_ride_duration_minutes is not None
            and route_duration_minutes > float(max_ride_duration_minutes)
        )

        routed_buses.append(
            {
                "bus_number": bus["bus_number"],
                "actual_capacity": int(bus.get("actual_capacity", 0)),
                "usable_capacity": int(bus.get("capacity", 0)),
                "total_students": total_students,
                "assigned_stops": pickup_order_ids,
                "ordered_stops": ordered_stops,
                "students_per_stop": students_per_stop,
                "route_order": [location_by_id[sid]["name"] for sid in route_order],
                "pickup_times": pickup_times,
                "arrival_time": arrival_time.strftime("%H:%M"),
                "primary_corridor": str(bus.get("primary_corridor", "")),
                "served_corridors": list(bus.get("served_corridors", [])),
                "route_distance_km": round(route_distance_km, 2),
                "route_duration_min": round(route_duration_minutes, 1),
                "boarding_duration_min": round(sum(boarding_seconds_per_stop) / 60.0, 1),
                "map_stops": map_stops,
                "map_route_geometry": route_geometry,
                "ride_duration_warning": bool(ride_duration_warning),
            }
        )

        if ride_duration_warning and max_ride_duration_minutes is not None:
            warnings.append(
                f"Bus {bus['bus_number']} exceeds max ride duration limit ({max_ride_duration_minutes} min)."
            )

        total_distance_km += route_distance_km
        total_duration_minutes += route_duration_minutes

    bus_count = len(routed_buses)
    avg_distance = total_distance_km / bus_count if bus_count else 0.0
    avg_duration = total_duration_minutes / bus_count if bus_count else 0.0

    return routed_buses, round(total_distance_km, 2), round(avg_distance, 2), round(avg_duration, 1)


def segment_overlap_score(route_a: List[Dict], route_b: List[Dict]) -> float:
    """Lightweight overlap heuristic based on nearby stop-to-stop segment midpoints."""
    def segments(stops: List[Dict]) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for idx in range(len(stops) - 1):
            a = (float(stops[idx]["lat"]), float(stops[idx]["lon"]))
            b = (float(stops[idx + 1]["lat"]), float(stops[idx + 1]["lon"]))
            pairs.append((a, b))
        return pairs

    seg_a = segments(route_a)
    seg_b = segments(route_b)
    if not seg_a or not seg_b:
        return 0.0

    overlap_hits = 0
    for a1, a2 in seg_a:
        mid_a = ((a1[0] + a2[0]) / 2.0, (a1[1] + a2[1]) / 2.0)
        for b1, b2 in seg_b:
            mid_b = ((b1[0] + b2[0]) / 2.0, (b1[1] + b2[1]) / 2.0)
            if haversine_km(mid_a[0], mid_a[1], mid_b[0], mid_b[1]) <= 0.75:
                overlap_hits += 1

    return round(overlap_hits / max(1, min(len(seg_a), len(seg_b))), 3)


def summarize_health_state(score: float) -> str:
    """Map weighted route quality score to a severity bucket."""
    return diagnostics_summarize_health_state(score)


def apply_penalty(score: float, penalties: List[Dict], category: str, points: float, message: str) -> float:
    """Apply a weighted penalty while tracking an explanatory warning."""
    return diagnostics_apply_penalty(score, penalties, category, points, message)


def route_quality_metrics(
    routed_buses: List[Dict],
    assigned_students_df: pd.DataFrame,
    bus_capacity: int,
    max_ride_duration_minutes: Optional[int] = None,
) -> Tuple[List[str], Dict]:
    """Compute per-bus and global quality diagnostics for optimized routes."""
    return diagnostics_route_quality_metrics(
        routed_buses,
        assigned_students_df,
        bus_capacity,
        max_ride_duration_minutes,
        haversine_km,
        COLLEGE_LAT,
        COLLEGE_LON,
        segment_overlap_score,
        summarize_health_state,
        apply_penalty,
    )


def build_assignments_and_stops_dict(
    assigned_students_df: pd.DataFrame,
    routed_buses: List[Dict],
) -> Tuple[List[Dict], Dict[str, Dict]]:
    """Build per-student assignment rows and stop-level student groupings."""
    stop_runtime: Dict[str, Dict] = {}
    for bus in routed_buses:
        bus_number = int(bus["bus_number"])
        bus_actual_capacity = int(bus.get("actual_capacity", 0))
        for stop in bus.get("map_stops", []):
            stop_runtime[str(stop["stop_id"])] = {
                "stop_name": str(stop["name"]),
                "stop_lat": float(stop["lat"]),
                "stop_lon": float(stop["lon"]),
                "bus_number": bus_number,
                "bus_actual_capacity": bus_actual_capacity,
                "pickup_time": str(stop["pickup_time"]),
            }

    assignments: List[Dict] = []
    stops_dict: Dict[str, Dict] = {}
    name_column = "student_name" if "student_name" in assigned_students_df.columns else "name"
    for _, row in assigned_students_df.iterrows():
        student_name = str(row[name_column])
        stop_id = str(row["stop_id"])
        source_file = str(row.get("source_file", ""))
        runtime = stop_runtime.get(stop_id)
        if runtime is None:
            continue

        assignment = {
            "student_name": student_name,
            "stop_name": runtime["stop_name"],
            "stop_lat": runtime["stop_lat"],
            "stop_lon": runtime["stop_lon"],
            "bus_number": runtime["bus_number"],
            "bus_actual_capacity": runtime.get("bus_actual_capacity", 0),
            "pickup_time": runtime["pickup_time"],
            "source_file": source_file,
        }
        assignments.append(assignment)

        stop_key = runtime["stop_name"]
        if stop_key not in stops_dict:
            stops_dict[stop_key] = {
                "stop_name": runtime["stop_name"],
                "lat": runtime["stop_lat"],
                "lon": runtime["stop_lon"],
                "students": [],
                "bus": runtime["bus_number"],
                "time": runtime["pickup_time"],
            }
        stops_dict[stop_key]["students"].append(student_name)

    return assignments, stops_dict


def write_assignments_csv(assignments: List[Dict]) -> None:
    """Write assignment export to static/assignments.csv."""
    ASSIGNMENTS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    export_rows = [
        {
            "student_name": item["student_name"],
            "stop_name": item["stop_name"],
            "bus_number": item["bus_number"],
            "pickup_time": item["pickup_time"],
            "source_file": item.get("source_file", ""),
        }
        for item in assignments
    ]
    pd.DataFrame(
        export_rows,
        columns=STUDENT_EXPORT_COLUMNS,
    ).to_csv(ASSIGNMENTS_CSV_PATH, index=False)


def write_driver_sheets(project_path: Path, buses: List[Dict], assignments: List[Dict]) -> None:
    """Generate per-bus driver sheets (CSV + printable HTML)."""
    persistence_write_driver_sheets(project_path=project_path, buses=buses, assignments=assignments)


def simulate_routes(
    current_routes: List[Dict],
    assignments: List[Dict],
    occupancy_percent: int,
    overflow_enabled: bool,
    overflow_limit: int,
    disabled_buses: List[int],
    bus_capacity: int,
    max_ride_duration_minutes: Optional[int] = DEFAULT_MAX_RIDE_DURATION_MINUTES,
    stop_dwell_seconds: Optional[int] = DEFAULT_STOP_DWELL_SECONDS,
    per_bus_actual_capacities: Optional[Dict[int, int]] = None,
) -> Dict:
    """Run lightweight scenario simulation on cloned route state."""
    return simulation_simulate_routes(
        current_routes=current_routes,
        occupancy_percent=occupancy_percent,
        overflow_enabled=overflow_enabled,
        overflow_limit=overflow_limit,
        disabled_buses=disabled_buses,
        bus_capacity=bus_capacity,
        build_capacity_profile=build_capacity_profile,
        max_ride_duration_minutes=max_ride_duration_minutes,
        stop_dwell_seconds=stop_dwell_seconds,
        per_bus_actual_capacities=per_bus_actual_capacities,
    )


def optimize_routes(
    students_df: pd.DataFrame,
    number_of_buses: int,
    bus_capacity: int,
    stop_source: str,
    occupancy_percent: int = int(TARGET_OCCUPANCY_RATIO * 100),
    overflow_enabled: bool = False,
    overflow_limit: int = 0,
    base_arrival_time: str = BASE_ARRIVAL_TIME,
    max_ride_duration_minutes: Optional[int] = DEFAULT_MAX_RIDE_DURATION_MINUTES,
    stop_dwell_seconds: Optional[int] = DEFAULT_STOP_DWELL_SECONDS,
    per_bus_actual_capacities: Optional[Dict[int, int]] = None,
    routing_policy_name: str = DEFAULT_ROUTING_POLICY,
) -> Dict:
    """Run complete optimization pipeline with OSRM first and fallback on failure."""
    warnings: List[str] = []
    routing_policy_name = normalize_routing_policy(routing_policy_name)
    capacity_profile = build_capacity_profile(
        bus_capacity=bus_capacity,
        occupancy_percent=occupancy_percent,
        overflow_enabled=overflow_enabled,
        overflow_limit=overflow_limit,
    )
    target_bus_load = int(capacity_profile["usable_capacity"])
    planned_capacity = int(capacity_profile["planned_capacity"])

    if bool(capacity_profile["overflow_enabled"]) and int(capacity_profile["overflow_limit"]) > int(math.floor(bus_capacity * 0.25)):
        warnings.append(
            f"Overflow limit exceeds 25% of bus capacity ({int(math.floor(bus_capacity * 0.25))})."
        )

    student_count = int(len(students_df))
    required_buses_without_overflow = int(math.ceil(student_count / max(1, planned_capacity)))
    required_buses_with_current_capacity = int(math.ceil(student_count / max(1, target_bus_load)))
    requested_seed_buses = min(max(1, int(number_of_buses)), max(1, required_buses_with_current_capacity))
    clustered_students_df, cluster_centers = cluster_students_geographically(
        students_df=students_df,
        n_clusters=max(1, required_buses_with_current_capacity),
        warnings=warnings,
    )

    stops_df, resolved_stop_source = build_stops_for_source(clustered_students_df, stop_source, warnings)
    corridor_count = max(
        CORRIDOR_SECTOR_MIN,
        min(CORRIDOR_SECTOR_MAX, max(1, required_buses_with_current_capacity)),
    )
    stops_df = assign_stop_corridors(stops_df, corridor_count=corridor_count)
    stops_df, projection_meta = build_bus_accessible_stops(
        students_df=clustered_students_df,
        stops_df=stops_df,
        stop_source=resolved_stop_source,
        warnings=warnings,
        routing_policy_name=routing_policy_name,
    )
    assigned_students_df = assign_students_to_stops(
        clustered_students_df,
        stops_df,
        warnings,
        cluster_centers=cluster_centers,
        projection_meta=projection_meta,
    )
    assigned_students_df = assigned_students_df.merge(
        stops_df[["stop_id", "lat", "lon", "road_class", "projected", "projection_walk_km", "dead_end_risk"]],
        on="stop_id",
        how="left",
        suffixes=("", "_stop"),
    )
    lat1 = np.radians(assigned_students_df["latitude"].to_numpy(dtype=float))
    lon1 = np.radians(assigned_students_df["longitude"].to_numpy(dtype=float))
    lat2 = np.radians(assigned_students_df["lat"].to_numpy(dtype=float))
    lon2 = np.radians(assigned_students_df["lon"].to_numpy(dtype=float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * (np.sin(dlon / 2.0) ** 2)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(np.maximum(1e-15, 1.0 - a)))
    assigned_students_df["walk_distance_km"] = 6371.0 * c

    chunks = build_stop_chunks(assigned_students_df, stops_df, target_bus_load)
    preferred_numbers = fleet_bus_numbers(requested_seed_buses)
    effective_actual_capacities: Dict[int, int] = {}
    requested_capacity_map = per_bus_actual_capacities or {}
    for bus_num in preferred_numbers:
        fleet_cap = fleet_capacity_for_bus(int(bus_num))
        configured_cap = int(requested_capacity_map.get(int(bus_num), 0)) if requested_capacity_map else 0
        chosen_cap = configured_cap if configured_cap > 0 else (fleet_cap if fleet_cap > 0 else int(bus_capacity))
        effective_actual_capacities[int(bus_num)] = int(max(1, chosen_cap))
    bus_usable_capacity_by_number = {
        int(bus_num): int(
            build_capacity_profile(
                bus_capacity=int(actual_cap),
                occupancy_percent=occupancy_percent,
                overflow_enabled=overflow_enabled,
                overflow_limit=overflow_limit,
            )["usable_capacity"]
        )
        for bus_num, actual_cap in effective_actual_capacities.items()
    }
    cluster_bus_numbers = {
        cluster_idx: int(preferred_numbers[cluster_idx])
        for cluster_idx in range(min(len(preferred_numbers), max(0, required_buses_with_current_capacity)))
    }
    buses, student_assignment_map = allocate_chunks_to_buses(
        chunks,
        requested_seed_buses,
        target_bus_load,
        preferred_bus_numbers=preferred_numbers,
        cluster_bus_numbers=cluster_bus_numbers,
        bus_usable_capacity_by_number=bus_usable_capacity_by_number,
        bus_actual_capacity_by_number=effective_actual_capacities,
        default_actual_capacity=int(bus_capacity),
        routing_policy_name=routing_policy_name,
    )
    if student_assignment_map:
        assigned_students_df["stop_id"] = assigned_students_df.index.map(
            lambda idx: student_assignment_map.get(int(idx), {}).get("stop_id", assigned_students_df.at[idx, "stop_id"])
        )

    used_chunk_rows = [
        chunk
        for bus in buses
        for chunk in bus["chunks"]
    ]
    stop_lookup = {
        str(chunk["stop_id"]): {
            "id": str(chunk["stop_id"]),
            "name": str(chunk["stop_name"]),
            "lat": float(chunk["lat"]),
            "lon": float(chunk["lon"]),
            "corridor": str(chunk.get("corridor", "")),
            "base_stop_id": str(chunk.get("base_stop_id", chunk["stop_id"])),
            "road_class": str(chunk.get("road_class", "tertiary")),
            "stop_source_type": str(chunk.get("stop_source_type", "generated")),
            "accessibility_verified": bool(chunk.get("accessibility_verified", False)),
            "accessibility_type": str(chunk.get("accessibility_type", "accessible")),
            "projected": bool(chunk.get("projected", False)),
            "projected_stop": bool(chunk.get("projected_stop", chunk.get("projected", False))),
            "projection_walk_km": float(chunk.get("projection_walk_km", 0.0)),
            "walking_distance_m": float(chunk.get("walking_distance_m", 0.0)),
            "original_stop_id": str(chunk.get("original_stop_id", chunk.get("base_stop_id", chunk["stop_id"]))),
            "original_lat": float(chunk.get("original_lat", chunk.get("lat", 0.0))),
            "original_lon": float(chunk.get("original_lon", chunk.get("lon", 0.0))),
            "road_suitability_score": float(chunk.get("road_suitability_score", 0.7)),
            "dead_end_risk": float(chunk.get("dead_end_risk", 0.0)),
        }
        for chunk in used_chunk_rows
    }

    route_locations = list(stop_lookup.values())
    route_locations.append(
        {
            "id": "COLLEGE",
            "name": COLLEGE_NAME,
            "lat": COLLEGE_LAT,
            "lon": COLLEGE_LON,
        }
    )

    route_matrix, matrix_source = get_travel_time_matrix(route_locations, warnings)

    routed_buses, total_distance, avg_distance, avg_duration = route_and_schedule_buses(
        buses=buses,
        route_locations=route_locations,
        route_matrix=route_matrix,
        warnings=warnings,
        base_arrival_time=base_arrival_time,
        max_ride_duration_minutes=max_ride_duration_minutes,
        stop_dwell_seconds=stop_dwell_seconds,
        routing_policy_name=routing_policy_name,
    )
    quality_warnings, quality_metrics = route_quality_metrics(
        routed_buses=routed_buses,
        assigned_students_df=assigned_students_df,
        bus_capacity=bus_capacity,
        max_ride_duration_minutes=max_ride_duration_minutes,
    )
    warnings.extend(quality_warnings)

    assignments, stops_dict = build_assignments_and_stops_dict(
        assigned_students_df=assigned_students_df,
        routed_buses=routed_buses,
    )
    write_assignments_csv(assignments)

    return {
        "buses": routed_buses,
        "total_buses_used": len(routed_buses),
        "total_route_distance": total_distance,
        "average_travel_distance": avg_distance,
        "average_travel_duration": avg_duration,
        "total_candidate_stops": int(len(stops_df)),
        "warnings": warnings,
        "matrix_source": matrix_source,
        "stop_source": resolved_stop_source,
        "assignments": assignments,
        "stops_dict": stops_dict,
        "capacity_profile": capacity_profile,
        "per_bus_actual_capacities": effective_actual_capacities,
        "required_buses_without_overflow": required_buses_without_overflow,
        "required_buses_with_current_capacity": required_buses_with_current_capacity,
        "bus_reduction_from_overflow": max(
            0, required_buses_without_overflow - required_buses_with_current_capacity
        )
        if bool(capacity_profile["overflow_enabled"])
        else 0,
        "base_arrival_time": base_arrival_time,
        "routing_policy": routing_policy_name,
        "quality_metrics": quality_metrics,
        "max_ride_duration_minutes": None if max_ride_duration_minutes is None else int(max_ride_duration_minutes),
        "stop_dwell_seconds": None if stop_dwell_seconds is None else int(stop_dwell_seconds),
    }


def load_project_payload(project_path: Path) -> Dict:
    """Load persisted project artifacts from disk."""
    return persistence_load_project_payload(project_path)


def project_cards() -> List[Dict]:
    """Build display cards for all saved projects."""
    return persistence_project_cards(
        projects_root=PROJECTS_ROOT,
        load_payload=load_project_payload,
        load_url_for_name=lambda name: url_for("load_project", project_name=name),
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["GET", "POST"])
def upload():
    stop_source = DEFAULT_STOP_SOURCE
    num_buses_value = ""
    capacity_value = ""
    occupancy_value = str(int(TARGET_OCCUPANCY_RATIO * 100))
    overflow_limit_value = "0"
    arrival_time_value = BASE_ARRIVAL_TIME
    overflow_enabled_value = False
    max_ride_duration_value = str(DEFAULT_MAX_RIDE_DURATION_MINUTES)
    stop_dwell_seconds_value = str(DEFAULT_STOP_DWELL_SECONDS)
    per_bus_capacities_value = ""
    routing_policy_value = DEFAULT_ROUTING_POLICY

    def render_upload_form() -> str:
        return render_template(
            "upload.html",
            default_stop_source=stop_source,
            bus_count_value=num_buses_value,
            capacity_value=capacity_value,
            occupancy_value=occupancy_value,
            overflow_limit_value=overflow_limit_value,
            arrival_time_value=arrival_time_value,
            overflow_enabled_value=overflow_enabled_value,
            max_ride_duration_value=max_ride_duration_value,
            stop_dwell_seconds_value=stop_dwell_seconds_value,
            per_bus_capacities_value=per_bus_capacities_value,
            routing_policy_value=routing_policy_value,
            routing_policy_options=ROUTING_POLICY_OPTIONS,
        )

    if request.method == "POST":
        try:
            try:
                num_buses = int(request.form.get("num_buses", 0))
                capacity_per_bus = int(request.form.get("capacity_per_bus", 0))
                occupancy_percent = int(request.form.get("occupancy_percent", int(TARGET_OCCUPANCY_RATIO * 100)))
                overflow_limit = int(request.form.get("overflow_limit", 0))
            except (TypeError, ValueError):
                raise ValueError("Bus count, capacity, occupancy, and overflow limit must be valid whole numbers.")

            stop_source = request.form.get("stop_source", DEFAULT_STOP_SOURCE)
            num_buses_value = str(request.form.get("num_buses", "")).strip()
            capacity_value = str(request.form.get("capacity_per_bus", "")).strip()
            occupancy_value = str(request.form.get("occupancy_percent", "")).strip()
            overflow_limit_value = str(request.form.get("overflow_limit", "")).strip()
            arrival_time_value = str(request.form.get("arrival_time", BASE_ARRIVAL_TIME)).strip() or BASE_ARRIVAL_TIME
            overflow_enabled_value = str(request.form.get("overflow_enabled", "")).strip().lower() in {"on", "true", "1", "yes"}
            max_ride_duration_value = str(request.form.get("max_ride_duration_minutes", DEFAULT_MAX_RIDE_DURATION_MINUTES)).strip()
            stop_dwell_seconds_value = str(request.form.get("stop_dwell_seconds", DEFAULT_STOP_DWELL_SECONDS)).strip()
            per_bus_capacities_value = str(request.form.get("per_bus_capacities", "")).strip()
            routing_policy_value = normalize_routing_policy(request.form.get("routing_policy", DEFAULT_ROUTING_POLICY))
            per_bus_capacity_map = parse_per_bus_capacities(per_bus_capacities_value)
            max_ride_duration_minutes = parse_optional_constraint_input(
                raw_value=max_ride_duration_value,
                default_value=DEFAULT_MAX_RIDE_DURATION_MINUTES,
                minimum_value=1,
                field_label="Max ride duration",
            )
            stop_dwell_seconds = parse_optional_constraint_input(
                raw_value=stop_dwell_seconds_value,
                default_value=DEFAULT_STOP_DWELL_SECONDS,
                minimum_value=0,
                field_label="Stop dwell time",
            )

            if num_buses <= 0:
                raise ValueError("Number of buses must be greater than 0.")
            if capacity_per_bus <= 0:
                raise ValueError("Capacity per bus must be greater than 0.")
            if occupancy_percent <= 0:
                raise ValueError("Occupancy % must be greater than 0.")
            if overflow_limit < 0:
                raise ValueError("Overflow limit must be 0 or greater.")
            uploaded_files = request.files.getlist("files")
            students_df, upload_summary = merge_uploaded_student_csvs(uploaded_files)
            result = optimize_routes(
                students_df=students_df,
                number_of_buses=num_buses,
                bus_capacity=capacity_per_bus,
                stop_source=stop_source,
                occupancy_percent=occupancy_percent,
                overflow_enabled=overflow_enabled_value,
                overflow_limit=overflow_limit,
                base_arrival_time=arrival_time_value,
                max_ride_duration_minutes=max_ride_duration_minutes,
                stop_dwell_seconds=stop_dwell_seconds,
                per_bus_actual_capacities=per_bus_capacity_map,
                routing_policy_name=routing_policy_value,
            )
            for warning in upload_summary["warnings"]:
                flash(warning, "warning")
            for warning in result["warnings"]:
                flash(warning, "warning")

            map_data = {
                "college": {
                    "name": COLLEGE_NAME,
                    "lat": COLLEGE_LAT,
                    "lon": COLLEGE_LON,
                },
                "buses": [
                    {
                        "bus_number": bus["bus_number"],
                        "map_stops": bus["map_stops"],
                        "map_route_geometry": bus["map_route_geometry"],
                    }
                    for bus in result["buses"]
                ],
                "stops_dict": result["stops_dict"],
            }

            return render_template(
                "results.html",
                buses=result["buses"],
                total_buses_used=result["total_buses_used"],
                total_route_distance=result["total_route_distance"],
                average_travel_distance=result["average_travel_distance"],
                average_travel_duration=result["average_travel_duration"],
                total_candidate_stops=result["total_candidate_stops"],
                college_name=COLLEGE_NAME,
                matrix_source=result["matrix_source"],
                stop_source=result["stop_source"],
                warnings=result["warnings"],
                map_data=map_data,
                routes_per_page=ROUTES_PER_PAGE,
                assignments=result["assignments"],
                configured_bus_capacity=capacity_per_bus,
                upload_summary=upload_summary,
                capacity_profile=result["capacity_profile"],
                required_buses_without_overflow=result["required_buses_without_overflow"],
                required_buses_with_current_capacity=result["required_buses_with_current_capacity"],
                bus_reduction_from_overflow=result["bus_reduction_from_overflow"],
                configured_arrival_time=result["base_arrival_time"],
                quality_metrics=result["quality_metrics"],
                configured_max_ride_duration=result["max_ride_duration_minutes"],
                configured_stop_dwell_seconds=result["stop_dwell_seconds"],
                configured_per_bus_capacities=result["per_bus_actual_capacities"],
                configured_routing_policy=result["routing_policy"],
                routing_policy_options=ROUTING_POLICY_OPTIONS,
                configured_max_ride_duration_label=format_constraint_for_display(
                    result["max_ride_duration_minutes"], "min"
                ),
                configured_stop_dwell_seconds_label=format_constraint_for_display(
                    result["stop_dwell_seconds"], "sec"
                ),
                merged_students=students_df[
                    ["student_name", "latitude", "longitude", "source_file"]
                ].to_dict(orient="records"),
                project_meta={},
                manual_plan_state={},
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return render_upload_form()
        except Exception:
            flash("Something went wrong while generating routes. Please try again.", "error")
            return render_upload_form()

    return render_upload_form()

@app.route("/results", methods=["GET"])
def results_page():
    return render_template(
        "results.html",
        buses=[],
        total_buses_used=0,
        total_route_distance=0,
        average_travel_distance=0,
        average_travel_duration=0,
        total_candidate_stops=0,
        college_name=COLLEGE_NAME,
        matrix_source="osrm",
        stop_source=DEFAULT_STOP_SOURCE,
        warnings=[],
        routes_per_page=ROUTES_PER_PAGE,
        assignments=[],
        configured_bus_capacity=0,
        capacity_profile=build_capacity_profile(
            bus_capacity=1,
            occupancy_percent=int(TARGET_OCCUPANCY_RATIO * 100),
            overflow_enabled=False,
            overflow_limit=0,
        ),
        required_buses_without_overflow=0,
        required_buses_with_current_capacity=0,
        bus_reduction_from_overflow=0,
        configured_arrival_time=BASE_ARRIVAL_TIME,
        quality_metrics={
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
        configured_max_ride_duration=DEFAULT_MAX_RIDE_DURATION_MINUTES,
        configured_stop_dwell_seconds=DEFAULT_STOP_DWELL_SECONDS,
        configured_per_bus_capacities={},
        configured_routing_policy=DEFAULT_ROUTING_POLICY,
        routing_policy_options=ROUTING_POLICY_OPTIONS,
        configured_max_ride_duration_label=format_constraint_for_display(
            DEFAULT_MAX_RIDE_DURATION_MINUTES, "min"
        ),
        configured_stop_dwell_seconds_label=format_constraint_for_display(
            DEFAULT_STOP_DWELL_SECONDS, "sec"
        ),
        upload_summary={
            "uploaded_files": 0,
            "total_students": 0,
            "invalid_rows_removed": 0,
            "duplicate_students_removed": 0,
            "warnings": [],
        },
        merged_students=[],
        project_meta={},
        manual_plan_state={},
        map_data={
            "college": {
                "name": COLLEGE_NAME,
                "lat": COLLEGE_LAT,
                "lon": COLLEGE_LON,
            },
            "buses": [],
            "stops_dict": {},
        },
    )


@app.route("/projects", methods=["GET"])
def projects_page():
    return render_template("projects.html", projects=project_cards())


@app.route("/fleet", methods=["GET", "POST"])
def fleet_page():
    if request.method == "POST":
        action = str(request.form.get("action", "")).strip().lower()
        fleet_df = load_fleet_df()

        if action == "add":
            try:
                bus_number = int(request.form.get("bus_number", "0"))
                if bus_number <= 0:
                    raise ValueError
            except ValueError:
                flash("Bus number must be a positive integer.", "error")
                return render_template(
                    "fleet.html",
                    **build_fleet_dashboard(fleet_df, request.args.get("filter", "all")),
                    active_filter=request.args.get("filter", "all"),
                )

            if bus_number in set(fleet_df["bus_number"].tolist()):
                flash("Bus number already exists.", "error")
            else:
                new_row = {
                    "bus_number": bus_number,
                    "registration_number": str(request.form.get("registration_number", "")).strip(),
                    "seating_capacity": int(pd.to_numeric(request.form.get("seating_capacity", "0"), errors="coerce") or 0),
                    "last_service_date": str(request.form.get("last_service_date", "")).strip(),
                    "next_service_due": str(request.form.get("next_service_due", "")).strip(),
                    "insurance_last_renewed": str(request.form.get("insurance_last_renewed", "")).strip(),
                    "insurance_expiry": str(request.form.get("insurance_expiry", "")).strip(),
                    "fc_last_done": str(request.form.get("fc_last_done", "")).strip(),
                    "fc_expiry": str(request.form.get("fc_expiry", "")).strip(),
                    "tax_last_paid": str(request.form.get("tax_last_paid", "")).strip(),
                    "tax_expiry": str(request.form.get("tax_expiry", "")).strip(),
                    "notes": str(request.form.get("notes", "")).strip(),
                }
                fleet_df = pd.concat([fleet_df, pd.DataFrame([new_row])], ignore_index=True)
                save_fleet_df(fleet_df.sort_values("bus_number"))
                flash("Bus added successfully.", "success")

        elif action == "edit":
            try:
                bus_number = int(request.form.get("bus_number", "0"))
            except ValueError:
                bus_number = 0

            if bus_number not in set(fleet_df["bus_number"].tolist()):
                flash("Bus not found.", "error")
            else:
                mask = fleet_df["bus_number"] == bus_number
                fleet_df.loc[mask, "registration_number"] = str(request.form.get("registration_number", "")).strip()
                fleet_df.loc[mask, "seating_capacity"] = int(pd.to_numeric(request.form.get("seating_capacity", "0"), errors="coerce") or 0)
                fleet_df.loc[mask, "last_service_date"] = str(request.form.get("last_service_date", "")).strip()
                fleet_df.loc[mask, "next_service_due"] = str(request.form.get("next_service_due", "")).strip()
                fleet_df.loc[mask, "insurance_last_renewed"] = str(request.form.get("insurance_last_renewed", "")).strip()
                fleet_df.loc[mask, "insurance_expiry"] = str(request.form.get("insurance_expiry", "")).strip()
                fleet_df.loc[mask, "fc_last_done"] = str(request.form.get("fc_last_done", "")).strip()
                fleet_df.loc[mask, "fc_expiry"] = str(request.form.get("fc_expiry", "")).strip()
                fleet_df.loc[mask, "tax_last_paid"] = str(request.form.get("tax_last_paid", "")).strip()
                fleet_df.loc[mask, "tax_expiry"] = str(request.form.get("tax_expiry", "")).strip()
                fleet_df.loc[mask, "notes"] = str(request.form.get("notes", "")).strip()
                save_fleet_df(fleet_df.sort_values("bus_number"))
                flash("Bus updated successfully.", "success")

        elif action == "delete":
            try:
                bus_number = int(request.form.get("bus_number", "0"))
            except ValueError:
                bus_number = 0
            before = len(fleet_df)
            fleet_df = fleet_df[fleet_df["bus_number"] != bus_number].copy()
            if len(fleet_df) == before:
                flash("Bus not found.", "error")
            else:
                save_fleet_df(fleet_df.sort_values("bus_number"))
                flash("Bus deleted successfully.", "success")

    filter_key = str(request.args.get("filter", "all")).strip().lower()
    if filter_key not in {"all", "expiring", "expired", "healthy"}:
        filter_key = "all"
    fleet = build_fleet_dashboard(load_fleet_df(), filter_key)
    return render_template(
        "fleet.html",
        rows=fleet["rows"],
        summary=fleet["summary"],
        active_filter=filter_key,
        fleet_columns=FLEET_COLUMNS,
    )


@app.route("/projects/<project_name>/load", methods=["GET"])
def load_project(project_name: str):
    project_path = project_dir_for_name(project_name)
    if not project_path.exists():
        flash("Project not found.", "error")
        return render_template("projects.html", projects=project_cards())

    try:
        payload = load_project_payload(project_path)
    except Exception:
        flash("Project could not be loaded.", "error")
        return render_template("projects.html", projects=project_cards())

    routes = payload["routes"]
    config = payload["config"]
    metrics = payload["metrics"]
    configured_max_ride_duration = coerce_optional_constraint(
        config.get("max_ride_duration_minutes", DEFAULT_MAX_RIDE_DURATION_MINUTES),
        DEFAULT_MAX_RIDE_DURATION_MINUTES,
    )
    configured_stop_dwell_seconds = coerce_optional_constraint(
        config.get("stop_dwell_seconds", DEFAULT_STOP_DWELL_SECONDS),
        DEFAULT_STOP_DWELL_SECONDS,
    )

    return render_template(
        "results.html",
        buses=routes.get("buses", []),
        total_buses_used=metrics.get("total_buses_used", 0),
        total_route_distance=metrics.get("total_route_distance", 0),
        average_travel_distance=metrics.get("average_travel_distance", 0),
        average_travel_duration=metrics.get("average_travel_duration", 0),
        total_candidate_stops=metrics.get("total_candidate_stops", 0),
        college_name=COLLEGE_NAME,
        matrix_source=metrics.get("matrix_source", "osrm"),
        stop_source=metrics.get("stop_source", DEFAULT_STOP_SOURCE),
        warnings=routes.get("warnings", []),
        map_data=routes.get("map_data", {"college": {"name": COLLEGE_NAME, "lat": COLLEGE_LAT, "lon": COLLEGE_LON}, "buses": [], "stops_dict": {}}),
        routes_per_page=ROUTES_PER_PAGE,
        assignments=payload["assignments"],
        configured_bus_capacity=int(config.get("bus_capacity", 0)),
        capacity_profile=build_capacity_profile(
            bus_capacity=int(config.get("bus_capacity", 1)),
            occupancy_percent=int(config.get("occupancy_percent", int(TARGET_OCCUPANCY_RATIO * 100))),
            overflow_enabled=bool(config.get("overflow_enabled", False)),
            overflow_limit=int(config.get("overflow_limit", 0)),
        ),
        required_buses_without_overflow=int(metrics.get("required_buses_without_overflow", metrics.get("total_buses_used", 0))),
        required_buses_with_current_capacity=int(metrics.get("required_buses_with_current_capacity", metrics.get("total_buses_used", 0))),
        bus_reduction_from_overflow=int(metrics.get("bus_reduction_from_overflow", 0)),
        configured_arrival_time=str(config.get("arrival_time", BASE_ARRIVAL_TIME)),
        quality_metrics=metrics.get(
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
        configured_max_ride_duration=configured_max_ride_duration,
        configured_stop_dwell_seconds=configured_stop_dwell_seconds,
        configured_per_bus_capacities=config.get("per_bus_actual_capacities", {}),
        configured_routing_policy=normalize_routing_policy(config.get("routing_policy", DEFAULT_ROUTING_POLICY)),
        routing_policy_options=ROUTING_POLICY_OPTIONS,
        configured_max_ride_duration_label=format_constraint_for_display(
            configured_max_ride_duration, "min"
        ),
        configured_stop_dwell_seconds_label=format_constraint_for_display(
            configured_stop_dwell_seconds, "sec"
        ),
        upload_summary={
            "uploaded_files": int(config.get("uploaded_files", 0)),
            "total_students": int(metrics.get("total_students", len(payload["merged_students"]))),
            "invalid_rows_removed": int(config.get("invalid_rows_removed", 0)),
            "duplicate_students_removed": int(config.get("duplicate_students_removed", 0)),
            "warnings": [],
        },
        merged_students=payload["merged_students"],
        project_meta={"project_name": project_path.name},
        manual_plan_state=routes.get("manual_plan_state", {}),
    )


@app.route("/api/projects/save", methods=["POST"])
def api_save_project():
    payload = request.get_json(silent=True) or {}
    project_name_raw = str(payload.get("project_name", "")).strip()
    sanitized_name = sanitize_project_name(project_name_raw)
    overwrite = bool(payload.get("overwrite", False))
    if not sanitized_name:
        return jsonify({"ok": False, "message": "Project Name is required."}), 400

    project_path = project_dir_for_name(sanitized_name)
    if project_path.exists() and not overwrite:
        return jsonify({"ok": False, "message": "Project already exists.", "code": "PROJECT_EXISTS"}), 409

    project_path.mkdir(parents=True, exist_ok=True)

    merged_students = payload.get("merged_students", [])
    assignments = payload.get("assignments", [])
    buses = payload.get("buses", [])
    map_data = payload.get("map_data", {})
    upload_summary = payload.get("upload_summary", {})
    metrics = payload.get("metrics", {})
    config_state = payload.get("config_state", {})
    simulation_state = payload.get("simulation_state", {})
    manual_plan_state = payload.get("manual_plan_state", {})
    persistence_write_project_artifacts(
        project_path=project_path,
        sanitized_name=sanitized_name,
        merged_students=merged_students,
        assignments=assignments,
        buses=buses,
        map_data=map_data,
        upload_summary=upload_summary,
        metrics=metrics,
        config_state={
            **config_state,
            "max_ride_duration_minutes": coerce_optional_constraint(
                config_state.get("max_ride_duration_minutes", DEFAULT_MAX_RIDE_DURATION_MINUTES),
                DEFAULT_MAX_RIDE_DURATION_MINUTES,
            ),
            "stop_dwell_seconds": coerce_optional_constraint(
                config_state.get("stop_dwell_seconds", DEFAULT_STOP_DWELL_SECONDS),
                DEFAULT_STOP_DWELL_SECONDS,
            ),
            "arrival_time": str(config_state.get("arrival_time", BASE_ARRIVAL_TIME)),
            "routing_policy": normalize_routing_policy(config_state.get("routing_policy", DEFAULT_ROUTING_POLICY)),
        },
        simulation_state=simulation_state,
        manual_plan_state=manual_plan_state,
        warnings=payload.get("warnings", []),
    )

    write_driver_sheets(project_path=project_path, buses=buses, assignments=assignments)

    return jsonify({"ok": True, "message": "Project saved.", "project_name": sanitized_name})


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    payload = request.get_json(silent=True) or {}
    try:
        max_ride_duration_minutes = parse_optional_constraint_input(
            raw_value=payload.get("max_ride_duration_minutes", DEFAULT_MAX_RIDE_DURATION_MINUTES),
            default_value=DEFAULT_MAX_RIDE_DURATION_MINUTES,
            minimum_value=1,
            field_label="Max ride duration",
        )
        stop_dwell_seconds = parse_optional_constraint_input(
            raw_value=payload.get("stop_dwell_seconds", DEFAULT_STOP_DWELL_SECONDS),
            default_value=DEFAULT_STOP_DWELL_SECONDS,
            minimum_value=0,
            field_label="Stop dwell time",
        )
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    result = simulate_routes(
        current_routes=payload.get("routes", []),
        assignments=payload.get("assignments", []),
        occupancy_percent=int(payload.get("occupancy_percent", 90)),
        overflow_enabled=bool(payload.get("overflow_enabled", False)),
        overflow_limit=int(payload.get("overflow_limit", 0)),
        disabled_buses=[int(v) for v in payload.get("disabled_buses", [])],
        bus_capacity=int(payload.get("bus_capacity", 0)),
        max_ride_duration_minutes=max_ride_duration_minutes,
        stop_dwell_seconds=stop_dwell_seconds,
        per_bus_actual_capacities={
            int(k): int(v)
            for k, v in (payload.get("per_bus_actual_capacities", {}) or {}).items()
            if str(k).strip()
        },
    )
    return jsonify({"ok": True, "result": result})


if __name__ == "__main__":
    app.run(debug=True)




