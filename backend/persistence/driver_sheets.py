from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd


def write_driver_sheets(project_path: Path, buses: List[Dict], assignments: List[Dict]) -> None:
    """Generate per-bus driver sheets (CSV + printable HTML)."""
    driver_dir = project_path / "driver_sheets"
    driver_dir.mkdir(parents=True, exist_ok=True)

    student_id_map: Dict[str, str] = {}
    for index, assignment in enumerate(assignments, start=1):
        key = f"{assignment.get('student_name', '')}|{assignment.get('source_file', '')}"
        if key not in student_id_map:
            student_id_map[key] = f"STD{index:04d}"

    for bus in buses:
        bus_number = int(bus.get("bus_number", 0))
        bus_actual_capacity = int(bus.get("actual_capacity", 0))
        stops = bus.get("ordered_stops", [])
        rows: List[Dict] = []
        for stop in stops:
            stop_name = str(stop.get("name", ""))
            pickup_time = str(stop.get("pickup_time", ""))
            bus_assignments = [
                a
                for a in assignments
                if int(a.get("bus_number", -1)) == bus_number and str(a.get("stop_name", "")) == stop_name
            ]
            for item in bus_assignments:
                student_key = f"{item.get('student_name', '')}|{item.get('source_file', '')}"
                rows.append(
                    {
                        "bus_number": bus_number,
                        "stop_number": int(stop.get("stop_number", 0)),
                        "stop_name": stop_name,
                        "pickup_time": pickup_time,
                        "student_count": int(stop.get("students_count", 0)),
                        "student_id": student_id_map.get(student_key, ""),
                        "student_name": item.get("student_name", ""),
                        "bus_actual_capacity": bus_actual_capacity,
                    }
                )

        csv_path = driver_dir / f"driver_sheet_bus_{bus_number}.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)

        html_rows = "".join(
            (
                "<tr>"
                f"<td>{r['stop_number']}</td>"
                f"<td>{r['stop_name']}</td>"
                f"<td>{r['pickup_time']}</td>"
                f"<td>{r['student_count']}</td>"
                f"<td>{r['student_id']}</td>"
                f"<td>{r['student_name']}</td>"
                "</tr>"
            )
            for r in rows
        )
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Driver Sheet Bus {bus_number}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; background: #fff; }}
h1 {{ margin: 0 0 6px 0; }}
h2 {{ margin: 0 0 16px 0; color: #444; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; font-size: 13px; }}
th {{ background: #f3f4f6; }}
.brand {{ font-size: 12px; color: #666; margin-bottom: 16px; }}
@media print {{ body {{ margin: 12px; }} }}
</style>
</head>
<body>
<h1>SmartRoute AI Driver Sheet</h1>
<h2>Bus {bus_number} | Capacity {bus_actual_capacity}</h2>
<div class="brand">Generated at {datetime.utcnow().isoformat()}Z</div>
<table>
<thead>
<tr>
<th>Stop Order</th><th>Stop Name</th><th>Pickup Time</th><th>Student Count</th><th>Student ID</th><th>Student Name</th>
</tr>
</thead>
<tbody>
{html_rows}
</tbody>
</table>
</body>
</html>"""
        (driver_dir / f"driver_sheet_bus_{bus_number}.html").write_text(
            html_content, encoding="utf-8"
        )

