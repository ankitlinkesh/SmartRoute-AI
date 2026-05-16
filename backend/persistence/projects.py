from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List

import pandas as pd


def load_project_payload(project_path: Path) -> Dict:
    routes_path = project_path / "routes.json"
    config_path = project_path / "config.json"
    metrics_path = project_path / "metrics.json"
    assignments_path = project_path / "assignments.csv"
    merged_students_path = project_path / "merged_students.csv"

    if not routes_path.exists() or not config_path.exists() or not metrics_path.exists():
        raise FileNotFoundError("Project artifacts are incomplete.")

    routes_payload = json.loads(routes_path.read_text(encoding="utf-8"))
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assignments_df = pd.read_csv(assignments_path) if assignments_path.exists() else pd.DataFrame()
    students_df = pd.read_csv(merged_students_path) if merged_students_path.exists() else pd.DataFrame()

    return {
        "routes": routes_payload,
        "config": config_payload,
        "metrics": metrics_payload,
        "assignments": assignments_df.to_dict(orient="records"),
        "merged_students": students_df.to_dict(orient="records"),
    }


def project_cards(
    *,
    projects_root: Path,
    load_payload: Callable[[Path], Dict],
    load_url_for_name: Callable[[str], str],
) -> List[Dict]:
    projects_root.mkdir(parents=True, exist_ok=True)
    cards: List[Dict] = []
    for project_path in sorted(projects_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not project_path.is_dir():
            continue
        try:
            payload = load_payload(project_path)
        except Exception:
            continue

        config = payload["config"]
        metrics = payload["metrics"]
        cards.append(
            {
                "project_name": project_path.name,
                "created_date": config.get("saved_at", ""),
                "total_students": int(metrics.get("total_students", len(payload["merged_students"]))),
                "total_buses": int(metrics.get("total_buses_used", metrics.get("buses_used", 0))),
                "occupancy_percent": int(config.get("occupancy_percent", 90)),
                "overflow_status": "ON" if bool(config.get("overflow_enabled", False)) else "OFF",
                "load_url": load_url_for_name(project_path.name),
            }
        )
    return cards

