import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import app
from backend.persistence.exports import write_project_artifacts
from backend.simulation.simulator import simulate_routes


class SmartRouteHardeningTests(unittest.TestCase):
    def test_project_config_persists_campus_and_routing_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir) / "ProjectA"
            write_project_artifacts(
                project_path=project_path,
                sanitized_name="ProjectA",
                merged_students=[],
                assignments=[],
                buses=[],
                map_data={"college": {"name": "Campus A", "lat": 12.9, "lon": 80.1}},
                upload_summary={"uploaded_files": 1},
                metrics={},
                config_state={
                    "city_name": "Chennai",
                    "campus_name": "Campus A",
                    "campus_lat": 12.9,
                    "campus_lon": 80.1,
                    "routing_policy": "strict_main_road",
                    "occupancy_percent": 90,
                    "overflow_enabled": False,
                    "overflow_limit": 0,
                    "bus_capacity": 40,
                },
                simulation_state={},
                manual_plan_state={},
                warnings=[],
            )

            config = json.loads((project_path / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(config["city_name"], "Chennai")
        self.assertEqual(config["campus_name"], "Campus A")
        self.assertEqual(config["campus_lat"], 12.9)
        self.assertEqual(config["campus_lon"], 80.1)
        self.assertEqual(config["routing_policy"], "strict_main_road")

    def test_verified_mtc_stop_bypasses_projection(self):
        students = pd.DataFrame(
            [{"student_name": "A", "latitude": 13.0, "longitude": 80.0, "source_file": "x.csv"}]
        )
        stops = pd.DataFrame(
            [
                {
                    "stop_id": "MTC1",
                    "stop_name": "Verified Stop",
                    "lat": 13.0,
                    "lon": 80.0,
                    "stop_source_type": "mtc",
                    "accessibility_verified": True,
                    "projected_stop": False,
                    "original_stop_id": "MTC1",
                    "original_lat": 13.0,
                    "original_lon": 80.0,
                }
            ]
        )

        warnings = []
        result, meta = app.build_bus_accessible_stops(
            students,
            stops,
            stop_source="mtc",
            warnings=warnings,
            routing_policy_name="strict_main_road",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(str(result.iloc[0]["stop_id"]), "MTC1")
        self.assertTrue(bool(result.iloc[0]["accessibility_verified"]))
        self.assertFalse(bool(result.iloc[0]["projected_stop"]))
        self.assertFalse(bool(meta["MTC1"]["projected"]))

    def test_simulation_counts_disabled_bus_students_as_unassigned_or_reassigned(self):
        routes = [
            {"bus_number": 1, "total_students": 40, "route_duration_min": 50, "route_distance_km": 20, "ordered_stops": []},
            {"bus_number": 2, "total_students": 40, "route_duration_min": 55, "route_distance_km": 22, "ordered_stops": []},
        ]
        result = simulate_routes(
            current_routes=routes,
            occupancy_percent=100,
            overflow_enabled=False,
            overflow_limit=0,
            disabled_buses=[2],
            bus_capacity=40,
            build_capacity_profile=app.build_capacity_profile,
            max_ride_duration_minutes=120,
            stop_dwell_seconds=20,
        )

        self.assertEqual(result["metrics"]["students_impacted_by_disabled_buses"], 40)
        self.assertGreaterEqual(result["metrics"]["unassigned_students"], 40)
        self.assertTrue(any("disabled" in warning.lower() for warning in result["warnings"]))

    def test_assignment_export_path_is_run_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = Path(tmpdir) / "run_a" / "assignments.csv"
            returned = app.write_assignments_csv(
                [{"student_name": "A", "stop_name": "S1", "bus_number": 1, "pickup_time": "07:30", "source_file": "a.csv"}],
                export_path=export_path,
            )

            self.assertEqual(returned, export_path)
            self.assertTrue(export_path.exists())
            self.assertFalse((Path(tmpdir) / "assignments.csv").exists())


if __name__ == "__main__":
    unittest.main()
