from typing import Callable, Dict, List, Tuple

import pandas as pd


def generate_candidate_stops_500m(
    students_df: pd.DataFrame,
    stop_spacing_km: float,
    haversine_km: Callable[[float, float, float, float], float],
) -> pd.DataFrame:
    """Create candidate stops with roughly one stop per 500m catchment."""
    sorted_students = students_df.sort_values(["latitude", "longitude"]).reset_index(drop=True)
    stops: List[Dict[str, float | str]] = []

    for _, student in sorted_students.iterrows():
        student_lat = float(student["latitude"])
        student_lon = float(student["longitude"])

        if any(
            haversine_km(student_lat, student_lon, float(stop["lat"]), float(stop["lon"]))
            < stop_spacing_km
            for stop in stops
        ):
            continue

        stops.append({"lat": student_lat, "lon": student_lon})

    if not stops and not sorted_students.empty:
        first_student = sorted_students.iloc[0]
        stops.append(
            {
                "lat": float(first_student["latitude"]),
                "lon": float(first_student["longitude"]),
            }
        )

    stops_df = pd.DataFrame(stops)
    stops_df["stop_id"] = [f"S{i + 1}" for i in range(len(stops_df))]
    stops_df["stop_name"] = stops_df["stop_id"]
    stops_df["stop_source_type"] = "generated"
    stops_df["accessibility_verified"] = False
    stops_df["projected_stop"] = False
    stops_df["original_stop_id"] = stops_df["stop_id"].astype(str)
    stops_df["original_lat"] = stops_df["lat"].astype(float)
    stops_df["original_lon"] = stops_df["lon"].astype(float)
    return stops_df


def load_mtc_stops(mtc_stops_path) -> pd.DataFrame:
    """Load local Chennai MTC stops from GTFS-style or OSM-export CSV headers."""
    if not mtc_stops_path.exists():
        raise FileNotFoundError("MTC stop dataset not found.")

    try:
        stops_df = pd.read_csv(mtc_stops_path)
    except Exception as exc:
        raise ValueError("Invalid MTC stop dataset.") from exc

    column_aliases = {
        "@id": "stop_id",
        "name": "stop_name",
        "@lat": "stop_lat",
        "@lon": "stop_lon",
    }
    stops_df = stops_df.rename(columns=column_aliases)

    required_columns = {"stop_id", "stop_name", "stop_lat", "stop_lon"}
    if not required_columns.issubset(stops_df.columns):
        raise ValueError("Invalid MTC stop dataset.")

    try:
        cleaned = stops_df[list(required_columns)].dropna().copy()
        cleaned["stop_id"] = cleaned["stop_id"].astype(str).str.strip()
        cleaned["stop_name"] = cleaned["stop_name"].astype(str).str.strip()
        cleaned["stop_lat"] = pd.to_numeric(cleaned["stop_lat"], errors="coerce")
        cleaned["stop_lon"] = pd.to_numeric(cleaned["stop_lon"], errors="coerce")
        cleaned = cleaned.dropna()
        cleaned = cleaned[
            cleaned["stop_lat"].between(-90, 90) & cleaned["stop_lon"].between(-180, 180)
        ]
        cleaned = cleaned[cleaned["stop_id"].ne("") & cleaned["stop_name"].ne("")]
        cleaned = cleaned.drop_duplicates(subset=["stop_id"]).reset_index(drop=True)
    except Exception as exc:
        raise ValueError("Invalid MTC stop dataset.") from exc

    if cleaned.empty:
        raise ValueError("Invalid MTC stop dataset.")

    cleaned = cleaned.rename(columns={"stop_lat": "lat", "stop_lon": "lon"})
    cleaned["stop_source_type"] = "mtc"
    cleaned["accessibility_verified"] = True
    cleaned["projected_stop"] = False
    cleaned["original_stop_id"] = cleaned["stop_id"].astype(str)
    cleaned["original_lat"] = cleaned["lat"].astype(float)
    cleaned["original_lon"] = cleaned["lon"].astype(float)
    return cleaned


def build_stops_for_source(
    students_df: pd.DataFrame,
    stop_source: str,
    warnings: List[str],
    mtc_stops_path,
    stop_spacing_km: float,
    haversine_km: Callable[[float, float, float, float], float],
) -> Tuple[pd.DataFrame, str]:
    """Build stop candidates from the requested source, with safe fallback."""
    if stop_source == "mtc":
        try:
            mtc_stops_df = load_mtc_stops(mtc_stops_path)
            return mtc_stops_df[
                [
                    "stop_id",
                    "stop_name",
                    "lat",
                    "lon",
                    "stop_source_type",
                    "accessibility_verified",
                    "projected_stop",
                    "original_stop_id",
                    "original_lat",
                    "original_lon",
                ]
            ], "mtc"
        except FileNotFoundError:
            warnings.append(
                "MTC stop dataset not found. Falling back to 500m generated stops."
            )
        except Exception:
            warnings.append(
                "Invalid MTC stop dataset. Using generated stops instead."
            )

    return generate_candidate_stops_500m(
        students_df,
        stop_spacing_km=stop_spacing_km,
        haversine_km=haversine_km,
    ), "500m"
