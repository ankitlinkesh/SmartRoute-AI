# SmartRoute AI

SmartRoute AI is a Flask-based transport optimization platform for student and shuttle routing. It combines corridor-aware assignment, OSRM road routing, operational capacity logic, and interactive dispatch tooling.

## Project Overview

The app helps admins upload student location CSVs, generate optimized bus routes, simulate operational changes, manually adjust routes, and save/load planning scenarios using file-based persistence.

## Features

- Multi-CSV student upload with validation, normalization, deduplication, and source tracking
- Corridor-aware routing with deterministic allocation
- Overflow-aware capacity allocation (affects initial bus allocation)
- OR-Tools stop sequence optimization with fallback sequencing
- OSRM integration for matrix/route geometry and ETA estimation
- Manual route editing with drag/reorder and dispatch controls
- Focused per-bus map view (`View On Map`) and show-all mode
- Route diagnostics (health scoring, warnings, quality breakdown)
- Simulation lab (occupancy, overflow, disabled bus scenarios)
- Save/load projects with CSV + JSON persistence
- Driver sheet generation (CSV + printable HTML)
- Per-bus capacity overrides
- Fleet management with renewal checklist tracking

## Architecture

```text
backend/
  preprocessing/
    validation.py
    stop_generation.py
  routing/
    route_sequencing.py
    capacity_assignment.py
  diagnostics/
    route_quality.py
    metrics.py
  persistence/
    projects.py
    exports.py
    driver_sheets.py
  simulation/
    simulator.py
  services/
    osrm_service.py
  utils/
    input_parsers.py
    project_paths.py
app.py
templates/
static/
```

## Screenshots

Add screenshots under `docs/screenshots/` and reference them here, for example:

- `docs/screenshots/upload-page.png`
- `docs/screenshots/results-dashboard.png`
- `docs/screenshots/fleet-management.png`

## Installation

1. Clone repository.
2. Create virtual environment.
3. Install dependencies.

```bash
python -m venv .venv
.venv\\Scripts\\activate   # Windows PowerShell
pip install -r requirements.txt
```

## Running the App

```bash
py app.py
```

Open: [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Route Optimization Flow

1. Upload one or many student CSV files.
2. Validate and normalize columns (`student_name`, `latitude`, `longitude`).
3. Merge, remove invalid rows, deduplicate by name + near-identical coordinates.
4. Build stops (MTC source or generated fallback).
5. Corridor-aware allocation with capacity/overflow logic.
6. Stop sequencing + OSRM geometry/ETA generation.
7. Diagnostics + route health scoring.
8. Render map, exports, and operational controls.

## Simulation Features

Simulation lab runs scenario analysis on cloned route state (without mutating the base plan):

- Occupancy changes
- Overflow toggle/limit changes
- Bus disable/breakdown what-if
- Comparison metrics (current vs simulated)

## Driver Sheets

Generated per bus in saved project folders:

- `driver_sheet_bus_<n>.csv`
- `driver_sheet_bus_<n>.html`

Includes stop order, pickup time, student list, and operational summary.

## Tech Stack

- Python, Flask
- Pandas, NumPy
- Scikit-learn (clustering, BallTree)
- OR-Tools (stop sequencing optimization)
- OSRM (road-aware matrix and route geometry)
- Leaflet + OpenStreetMap
- CSV/JSON file-based persistence

## Future Improvements

- Background task queue for very large runs
- Enhanced operational reporting dashboards
- Role-based admin workflows
- Stronger validation tooling and test suite expansion
- Optional plug-in architecture for city-specific transport policies
