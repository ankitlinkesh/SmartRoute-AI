from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import requests


BUS_FRIENDLY_HIGHWAYS = {
    "motorway": "primary",
    "trunk": "primary",
    "primary": "primary",
    "secondary": "secondary",
    "tertiary": "tertiary",
    "unclassified": "tertiary",
}
NARROW_HIGHWAYS = {
    "residential": "residential",
    "living_street": "residential",
    "service": "service/internal",
    "pedestrian": "service/internal",
    "track": "service/internal",
    "path": "service/internal",
}


def _cache_key(lat: float, lon: float) -> str:
    return f"{round(float(lat), 5)},{round(float(lon), 5)}"


def load_road_access_cache(cache_path: Path) -> Dict[str, Dict]:
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_road_access_cache(cache_path: Path, cache: Dict[str, Dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def classify_nearest_road_cached(
    *,
    lat: float,
    lon: float,
    cache: Dict[str, Dict],
    overpass_url: str,
    timeout_seconds: int,
    radius_m: int,
) -> Optional[Dict]:
    """Return cached/Overpass road suitability near a generated pickup point."""
    key = _cache_key(lat, lon)
    if key in cache:
        cached = cache[key]
        return cached if isinstance(cached, dict) else None

    query = f"""
    [out:json][timeout:{max(1, int(timeout_seconds))}];
    way(around:{max(20, int(radius_m))},{float(lat)},{float(lon)})[highway];
    out tags center 12;
    """
    response = requests.post(overpass_url, data={"data": query}, timeout=max(1, int(timeout_seconds)))
    response.raise_for_status()
    payload = response.json()
    candidates = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {}) or {}
        highway = str(tags.get("highway", "")).strip().lower()
        if not highway:
            continue
        road_class = BUS_FRIENDLY_HIGHWAYS.get(highway) or NARROW_HIGHWAYS.get(highway)
        if not road_class:
            continue
        rank = {"primary": 0, "secondary": 1, "tertiary": 2, "residential": 3, "service/internal": 4}[road_class]
        candidates.append((rank, road_class, highway, str(tags.get("name", ""))))

    if not candidates:
        return None
    _, road_class, highway, road_name = sorted(candidates, key=lambda item: (item[0], item[2], item[3]))[0]
    result = {
        "road_class": road_class,
        "osm_highway": highway,
        "road_name": road_name,
        "source": "osm_overpass_cache",
    }
    cache[key] = result
    return result
