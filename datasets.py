"""Local tabular imports and evaluation against the frozen study pipelines."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

import defusedxml  # openpyxl uses this installed parser for untrusted workbook XML.
import numpy as np
import openpyxl
import pandas as pd
from fastapi import HTTPException
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

FEATURES = [f"X{i}" for i in range(1, 9)]
TARGETS = ["Y1", "Y2"]
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLS = 64


def write_json(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def records(frame: pd.DataFrame):
    return json.loads(frame.to_json(orient="records", double_precision=15))


def folder(root: Path, dataset_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", dataset_id):
        raise HTTPException(404, "Dataset not found.")
    path = root / dataset_id
    if not (path / "metadata.json").is_file():
        raise HTTPException(404, "Dataset not found.")
    return path


def parse_table(content: bytes, suffix: str):
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(413, "Choose a nonempty file no larger than 5 MiB.")
    sheet = None
    try:
        if suffix == ".csv":
            reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
            raw_rows = iter(reader)
            workbook = None
        elif suffix == ".xlsx":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if len(archive.infolist()) > 1024 or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError("The expanded workbook is too large; export a smaller table.")
                if "xl/workbook.xml" not in archive.namelist():
                    raise ValueError("This file is not an XLSX workbook.")
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
            worksheet = workbook.worksheets[0]
            sheet = worksheet.title
            if worksheet.max_column and worksheet.max_column > MAX_COLS:
                workbook.close()
                raise ValueError("The first worksheet has more than 64 columns.")
            raw_rows = worksheet.iter_rows(values_only=True)
        else:
            raise ValueError("Only UTF-8 CSV and XLSX files are supported.")
        try:
            header = list(next(raw_rows))
            if not header or len(header) > MAX_COLS:
                raise ValueError("Provide a header with 1–64 columns.")
            columns = [str(value).strip() if value is not None else "" for value in header]
            if any(not value or len(value) > 160 for value in columns) or len(set(columns)) != len(columns):
                raise ValueError("Column names must be nonempty, unique, and at most 160 characters.")
            rows, source_rows, blank_rows = [], [], 0
            for row_number, raw in enumerate(raw_rows, start=2):
                if row_number > MAX_ROWS + 1:
                    raise ValueError("The file exceeds 10,000 data rows; split it into smaller files.")
                row = list(raw)
                if not any(value is not None and str(value).strip() for value in row):
                    blank_rows += 1
                    continue
                if len(row) != len(columns):
                    raise ValueError(f"Data row {row_number} does not match the header width.")
                rows.append(row)
                source_rows.append(row_number)
            if not rows:
                raise ValueError("The table has no nonempty data records.")
        finally:
            if workbook is not None:
                workbook.close()
    except HTTPException:
        raise
    except (ValueError, UnicodeError, csv.Error, zipfile.BadZipFile, StopIteration, KeyError, IndexError) as exc:
        raise HTTPException(400, f"Cannot read this table: {exc or 'the file is empty'}. Use the provided template.") from exc
    except Exception as exc:
        raise HTTPException(400, "Cannot read this workbook. Re-export its first sheet as CSV or XLSX.") from exc
    return pd.DataFrame(rows, columns=columns), source_rows, sheet, blank_rows


def inspect_upload(root: Path, filename: str, content: bytes):
    safe_name = Path(filename.replace("\\", "/")).name[:200] or "dataset"
    suffix = Path(safe_name).suffix.lower()
    frame, source_rows, sheet, blank_rows = parse_table(content, suffix)
    dataset_id = uuid.uuid4().hex
    path = root / dataset_id
    path.mkdir(parents=True)
    (path / ("source" + suffix)).write_bytes(content)
    from datetime import datetime, timezone
    types = {}
    for column in frame:
        values = frame[column].dropna()
        values = values[values.map(lambda value: bool(str(value).strip()))]
        numeric = pd.to_numeric(values, errors="coerce").notna()
        types[column] = "empty" if not len(values) else "boolean" if values.map(lambda value: isinstance(value, (bool, np.bool_))).all() else "numeric" if numeric.all() else "mixed" if numeric.any() else "text"
    metadata = {
        "id": dataset_id, "name": safe_name, "suffix": suffix,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
        "rows": len(frame), "columns": list(frame.columns), "sheet": sheet,
        "blank_rows": blank_rows,
        "types": types,
    }
    write_json(path / "metadata.json", metadata)
    return {**metadata, "preview": records(frame.head(20)), "source_rows": source_rows[:20]}


def list_datasets(root: Path):
    result = []
    for path in root.glob("*/metadata.json"):
        try:
            item = read_json(path)
            item["has_results"] = (path.parent / "results.json").is_file()
            result.append(item)
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda item: item["created_at"], reverse=True)


def load_source(path: Path, metadata: dict):
    try:
        content = (path / ("source" + metadata["suffix"])).read_bytes()
    except OSError as exc:
        raise HTTPException(410, "The saved original file is unavailable. Import your dataset again.") from exc
    if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
        raise HTTPException(409, "The saved original file has changed. Import it again to establish a new checksum and evaluation.")
    return parse_table(content, metadata["suffix"])


def inspect_saved(root: Path, dataset_id: str):
    path = folder(root, dataset_id)
    metadata = read_json(path / "metadata.json")
    frame, source_rows, _, _ = load_source(path, metadata)
    config = read_json(path / "config.json") if (path / "config.json").exists() else None
    return {**metadata, "preview": records(frame.head(20)), "source_rows": source_rows[:20], "config": config}


def validate(root: Path, dataset_id: str, config: dict, study):
    path = folder(root, dataset_id)
    metadata = read_json(path / "metadata.json")
    frame, source_rows, _, _ = load_source(path, metadata)
    mapping = {key: value for key, value in config["mapping"].items() if value}
    if not set(FEATURES).issubset(mapping) or not set(mapping).issubset(FEATURES + TARGETS):
        raise HTTPException(422, "Map all eight building inputs; only X1–X8 and optional Y1/Y2 are accepted.")
    if len(set(mapping.values())) != len(mapping) or any(column not in frame for column in mapping.values()):
        raise HTTPException(422, "Each mapped input or target must use its own existing source column.")
    numeric = pd.DataFrame({key: pd.to_numeric(frame[column], errors="coerce") for key, column in mapping.items()})
    errors = [[] for _ in range(len(frame))]
    warnings = [[] for _ in range(len(frame))]

    def mark(mask, message, destination=errors):
        for index in np.flatnonzero(np.asarray(mask)):
            destination[int(index)].append(message)

    for key in FEATURES:
        original = frame[mapping[key]]
        boolean = original.map(lambda value: isinstance(value, (bool, np.bool_)))
        mark(~np.isfinite(numeric[key]) | boolean, f"{key}: a finite numeric value is required")
        # Tree predictors convert inputs to float32; reject values that cannot survive that conversion.
        mark(numeric[key].abs() > np.finfo(np.float32).max, f"{key}: exceeds the model's supported numeric range")
    for key in ["X1", "X2", "X3", "X4", "X5"]:
        mark(np.isfinite(numeric[key]) & (numeric[key] <= 0), f"{key}: must be positive")
    mark(numeric.X1 > 1, "X1: relative compactness must be at most 1")
    mark((numeric.X7 < 0) | (numeric.X7 > 1), "X7: enter a fraction between 0 and 1, not a percentage")
    mark(np.isfinite(numeric.X6) & ~numeric.X6.isin([2, 3, 4, 5]), "X6: supported orientation codes are 2, 3, 4, 5")
    mark(np.isfinite(numeric.X8) & ~numeric.X8.isin([0, 1, 2, 3, 4, 5]), "X8: supported distribution codes are 0–5")
    mark(((numeric.X7 == 0) & (numeric.X8 != 0)) | ((numeric.X7 > 0) & (numeric.X8 == 0)), "X7/X8: zero glazing requires distribution 0; positive glazing requires 1–5")
    duplicated = numeric[FEATURES].duplicated(keep=False)
    mark(duplicated, "Repeated input configuration; retained", warnings)
    for key in ["X1", "X2", "X3", "X4", "X5", "X7"]:
        mark((numeric[key] < study.df[key].min()) | (numeric[key] > study.df[key].max()), f"{key} outside benchmark range", warnings)
    geometry = set(map(tuple, study.df[FEATURES[:5]].to_numpy()))
    partitions = {tuple(row): partition for row, partition in zip(study.df[FEATURES].to_numpy(), study.splits.partition)}
    matches = []
    for index, row in enumerate(numeric[FEATURES].to_numpy()):
        match = partitions.get(tuple(row))
        matches.append(match)
        if tuple(row[:5]) not in geometry:
            warnings[index].append("Geometry absent from the 12 benchmark shapes")
        if match:
            warnings[index].append("Input configuration appears in the benchmark " + match + " partition")
    reference_counts = {}
    valid = np.array([not row for row in errors], dtype=bool)
    for key in TARGETS:
        if key in numeric:
            boolean = frame[mapping[key]].map(lambda value: isinstance(value, (bool, np.bool_)))
            reference_valid = np.isfinite(numeric[key]) & ~boolean & (numeric[key] >= 0) & (numeric[key] <= np.finfo(np.float32).max)
            mark(~reference_valid, key + ": missing or invalid reference; excluded from this target's metrics", warnings)
            numeric.loc[~reference_valid, key] = np.nan
            reference_counts[key] = int((reference_valid & valid).sum())
    issues = [
        {"source_row": source_rows[index], "errors": errors[index], "warnings": warnings[index]}
        for index in range(len(frame)) if errors[index] or warnings[index]
    ]
    comparable = bool(config["comparable"] and config["response_units"].strip() and config["response_definition"].strip())
    report = {
        "dataset_id": dataset_id, "name": metadata["name"], "total_rows": len(frame),
        "source_sha256": metadata["sha256"], "source_sheet": metadata["sheet"],
        "valid_rows": int(valid.sum()), "invalid_rows": int((~valid).sum()),
        "warning_rows": sum(bool(row) for row in warnings), "duplicate_rows": int(duplicated.sum()),
        "development_matches": matches.count("development"), "test_matches": matches.count("test"),
        "reference_counts": reference_counts, "metrics_enabled": comparable and any(reference_counts.values()),
        "issues": issues[:100], "issue_rows_total": len(issues),
        "preview": records(numeric.head(20)), "source_rows": source_rows[:20],
    }
    return numeric, valid, source_rows, errors, warnings, matches, report


def evaluate(root: Path, dataset_id: str, config: dict, study):
    numeric, valid, source_rows, errors, warnings, matches, report = validate(root, dataset_id, config, study)
    if not valid.any():
        raise HTTPException(422, "No valid input records remain. Correct the validation errors first.")
    if not valid.all() and not config["skip_invalid_rows"]:
        raise HTTPException(422, "Some input rows are invalid. Correct them or explicitly choose Evaluate valid rows only.")
    predictions, elapsed = study.predict(numeric.loc[valid, FEATURES])
    output = numeric.copy()
    output.insert(0, "source_row", source_rows)
    output["status"] = np.where(valid, "predicted", "rejected")
    output["benchmark_match"] = [value or "none" for value in matches]
    output["issues"] = ["; ".join(a + b) for a, b in zip(errors, warnings)]
    metrics = []
    for model in ["MLR", "DT", "RF"]:
        for target, label in [("Y1", "heating"), ("Y2", "cooling")]:
            column = f"{model}_{target}_predicted"
            output[column] = np.nan
            output.loc[valid, column] = [row["models"][model][label] for row in predictions]
            if report["metrics_enabled"] and target in numeric:
                eligible = valid & np.isfinite(numeric[target])
                y = numeric.loc[eligible, target]
                p = output.loc[eligible, column]
                if len(y):
                    r2 = float(r2_score(y, p)) if len(y) >= 2 and y.nunique() > 1 else None
                    if r2 is not None and not np.isfinite(r2):
                        r2 = None
                    metrics.append({
                        "model": model, "target": target, "n": len(y),
                        "MAE": float(mean_absolute_error(y, p)),
                        "RMSE": float(np.sqrt(mean_squared_error(y, p))), "R2": r2,
                        "R2_note": None if r2 is not None else "R² requires at least two reference values with nonzero variation.",
                    })
    output = output.replace([np.inf, -np.inf], np.nan)
    from datetime import datetime, timezone
    response = {
        **report, "evaluated_at": datetime.now(timezone.utc).isoformat(), "config": config,
        "inference_ms": elapsed, "metrics": metrics, "rows": records(output),
        "model_provenance": {key: study.metadata[key] for key in ["seed", "python", "sklearn", "numpy", "pandas", "data_sha256"]},
        "comparability": "User-declared; definitions and units are not independently verified." if report["metrics_enabled"] else "Reference definitions/units not confirmed, or no usable reference loads. Predictions only.",
        "notice": "Frozen simulation-trained models. These results are an external-data experiment, not certification of real-building performance.",
    }
    path = folder(root, dataset_id)
    temporary = path / "results.csv.tmp"
    output.to_csv(temporary, index=False)
    temporary.replace(path / "results.csv")
    write_json(path / "config.json", config)
    write_json(path / "results.json", response)
    return response
