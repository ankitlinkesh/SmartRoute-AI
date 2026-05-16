from __future__ import annotations

import re
from pathlib import Path


def sanitize_project_name(project_name: str) -> str:
    cleaned = str(project_name or "").strip().replace(" ", "_")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned


def project_dir_for_name(projects_root: Path, project_name: str) -> Path:
    return projects_root / sanitize_project_name(project_name)

