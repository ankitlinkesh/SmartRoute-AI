from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import requests


def build_osrm_coord_string(points: List[Dict]) -> str:
    return ";".join(f"{p['lon']},{p['lat']}" for p in points)


def chunk_items(items: List, size: int) -> List[List]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def osrm_get_json(
    path: str,
    params: Optional[Dict],
    *,
    osrm_base_url: str,
    timeout_seconds: int,
    max_retries: int,
    call_delay_seconds: float,
    cooldown_seconds: int,
    down_until_ref: Dict[str, float],
) -> Optional[Dict]:
    if time.time() < float(down_until_ref.get("value", 0.0)):
        return None

    url = f"{osrm_base_url}{path}"
    for attempt in range(max_retries):
        time.sleep(call_delay_seconds)
        try:
            response = requests.get(url, params=params, timeout=timeout_seconds)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt == max_retries - 1:
                down_until_ref["value"] = time.time() + cooldown_seconds
                return None
    return None


def get_osrm_table_block(
    origins: List[Dict],
    destinations: List[Dict],
    *,
    table_batch_size: int,
    osrm_json_getter: Callable[[str, Optional[Dict]], Optional[Dict]],
    traffic_inflator: Callable[[float], float],
) -> Optional[List[List[Dict]]]:
    all_points = origins + destinations
    if len(origins) > table_batch_size or len(destinations) > table_batch_size:
        return None

    coord_string = build_osrm_coord_string(all_points)
    sources = ";".join(str(i) for i in range(len(origins)))
    destinations_idx = ";".join(str(i + len(origins)) for i in range(len(destinations)))

    payload = osrm_json_getter(
        f"/table/v1/driving/{coord_string}",
        {
            "annotations": "duration,distance",
            "sources": sources,
            "destinations": destinations_idx,
        },
    )
    if not payload or payload.get("code") != "Ok":
        return None
    durations = payload.get("durations")
    distances = payload.get("distances")
    if durations is None or distances is None:
        return None

    matrix: List[List[Dict]] = []
    for i in range(len(origins)):
        row: List[Dict] = []
        for j in range(len(destinations)):
            dsec = durations[i][j]
            dmet = distances[i][j]
            if dsec is None or dmet is None:
                return None
            row.append(
                {
                    "travel_seconds": traffic_inflator(float(dsec)),
                    "distance_km": float(dmet) / 1000.0,
                    "source": "osrm",
                }
            )
        matrix.append(row)
    return matrix


def get_osrm_table_matrix(
    origins: List[Dict],
    destinations: List[Dict],
    *,
    table_batch_size: int,
    get_table_block: Callable[[List[Dict], List[Dict]], Optional[List[List[Dict]]]],
) -> Optional[List[List[Dict]]]:
    if not origins or not destinations:
        return []

    full_matrix = [
        [{"travel_seconds": 0.0, "distance_km": 0.0, "source": "osrm"} for _ in destinations]
        for _ in origins
    ]

    origin_chunks = chunk_items(list(enumerate(origins)), table_batch_size)
    destination_chunks = chunk_items(list(enumerate(destinations)), table_batch_size)

    for origin_chunk in origin_chunks:
        for destination_chunk in destination_chunks:
            origin_block = [item for _, item in origin_chunk]
            destination_block = [item for _, item in destination_chunk]
            block_matrix = get_table_block(origin_block, destination_block)
            if block_matrix is None:
                return None
            for origin_local_idx, (origin_global_idx, _) in enumerate(origin_chunk):
                for destination_local_idx, (destination_global_idx, _) in enumerate(destination_chunk):
                    full_matrix[origin_global_idx][destination_global_idx] = block_matrix[origin_local_idx][
                        destination_local_idx
                    ]

    return full_matrix

