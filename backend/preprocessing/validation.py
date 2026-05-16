from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


def normalize_student_column_name(column_name: str) -> str:
    """Normalize CSV headers before alias matching."""
    return (
        str(column_name)
        .strip()
        .lower()
        .replace("\ufeff", "")
        .replace(" ", "_")
        .replace("-", "_")
    )


def get_student_column_mapping(
    df: pd.DataFrame,
    student_column_aliases: Dict[str, List[str]],
) -> Tuple[Dict[str, str], List[str]]:
    """Resolve uploaded CSV columns to canonical student field names."""
    normalized_lookup: Dict[str, str] = {}
    for column in df.columns:
        normalized = normalize_student_column_name(column)
        if normalized not in normalized_lookup:
            normalized_lookup[normalized] = column

    mapping: Dict[str, str] = {}
    missing: List[str] = []
    for canonical_name, aliases in student_column_aliases.items():
        source_column = next(
            (normalized_lookup[alias] for alias in aliases if alias in normalized_lookup),
            None,
        )
        if source_column is None:
            missing.append(canonical_name)
        else:
            mapping[canonical_name] = source_column

    return mapping, missing


def parse_student_csv(
    file_obj,
    source_filename: str,
    student_column_aliases: Dict[str, List[str]],
) -> Tuple[pd.DataFrame, int]:
    """Load one student CSV, normalize schema, and return valid rows plus invalid count."""
    df = pd.read_csv(file_obj)
    if df.empty:
        return pd.DataFrame(columns=["student_name", "latitude", "longitude", "source_file"]), 0

    column_mapping, missing = get_student_column_mapping(df, student_column_aliases)
    if missing:
        missing_label = ", ".join(sorted(missing))
        raise ValueError(f"{source_filename} is missing required columns: {missing_label}")

    cleaned = pd.DataFrame(
        {
            "student_name": df[column_mapping["student_name"]],
            "latitude": df[column_mapping["latitude"]],
            "longitude": df[column_mapping["longitude"]],
        }
    )
    cleaned["student_name"] = cleaned["student_name"].astype("string").fillna("").str.strip()
    cleaned["latitude"] = pd.to_numeric(cleaned["latitude"], errors="coerce")
    cleaned["longitude"] = pd.to_numeric(cleaned["longitude"], errors="coerce")

    invalid_rows = (
        cleaned["student_name"].eq("")
        | cleaned["latitude"].isna()
        | cleaned["longitude"].isna()
        | ~cleaned["latitude"].between(-90, 90)
        | ~cleaned["longitude"].between(-180, 180)
    )
    invalid_count = int(invalid_rows.sum())

    cleaned = cleaned.loc[
        ~invalid_rows,
        ["student_name", "latitude", "longitude"],
    ].copy()
    cleaned["source_file"] = source_filename

    return cleaned, invalid_count


def merge_uploaded_student_csvs(
    uploaded_files: List,
    student_column_aliases: Dict[str, List[str]],
) -> Tuple[pd.DataFrame, Dict]:
    """Merge one or many uploaded student CSVs into a routing-ready dataframe."""
    selected_files = []
    for uploaded_file in uploaded_files:
        if not uploaded_file:
            continue
        filename = getattr(uploaded_file, "filename", None)
        if filename is not None and filename == "":
            continue
        selected_files.append(uploaded_file)

    if not selected_files:
        raise ValueError("Please choose at least one CSV file before submitting.")

    valid_frames: List[pd.DataFrame] = []
    invalid_rows_removed = 0
    file_warnings: List[str] = []

    for file_index, uploaded_file in enumerate(selected_files, start=1):
        raw_filename = (
            getattr(uploaded_file, "filename", None)
            or getattr(uploaded_file, "name", None)
            or f"uploaded_{file_index}.csv"
        )
        source_filename = Path(str(raw_filename)).name or f"uploaded_{file_index}.csv"
        try:
            parsed_df, invalid_count = parse_student_csv(
                uploaded_file,
                source_filename,
                student_column_aliases,
            )
        except Exception as exc:
            file_warnings.append(f"{source_filename} skipped: {exc}")
            continue

        invalid_rows_removed += invalid_count
        if not parsed_df.empty:
            valid_frames.append(parsed_df)

    if not valid_frames:
        raise ValueError("No valid student data found.")

    merged_df = pd.concat(valid_frames, ignore_index=True, copy=False)
    duplicate_keys = pd.DataFrame(
        {
            "student_name": (
                merged_df["student_name"]
                .astype("string")
                .str.strip()
                .str.casefold()
                .str.replace(r"\s+", " ", regex=True)
            ),
            "latitude": merged_df["latitude"].round(5),
            "longitude": merged_df["longitude"].round(5),
        }
    )
    duplicate_rows = duplicate_keys.duplicated(keep="first")
    duplicate_rows_removed = int(duplicate_rows.sum())

    merged_df = merged_df.loc[
        ~duplicate_rows,
        ["student_name", "latitude", "longitude", "source_file"],
    ].reset_index(drop=True)
    merged_df["name"] = merged_df["student_name"]

    upload_summary = {
        "uploaded_files": len(selected_files),
        "total_students": int(len(merged_df)),
        "invalid_rows_removed": invalid_rows_removed,
        "duplicate_students_removed": duplicate_rows_removed,
        "warnings": file_warnings,
    }

    return merged_df, upload_summary
