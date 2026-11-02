"""Building Energy Lab: one local server for the study and external-data testing."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import joblib
import numpy as np
import pandas as pd
import sklearn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from starlette.middleware.trustedhost import TrustedHostMiddleware
from threadpoolctl import threadpool_limits

import datasets
from study import FEATURES, NAMES, ROOT, load_data

APP_DIR = Path(__file__).resolve().parent
DATASET_ROOT = APP_DIR / "user_data"
METHODS = ["MLR", "DT", "RF"]
LOCAL_HOSTS = ["127.0.0.1", "localhost", "testserver"]
PUBLIC_HOST = os.environ.get("ENERGY_PUBLIC_HOST", "")
if PUBLIC_HOST and not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", PUBLIC_HOST):
    raise RuntimeError("ENERGY_PUBLIC_HOST must be one hostname without a scheme, port, path, or wildcard.")


class Study:
    def __init__(self):
        out = ROOT / "results"
        required = [ROOT / "data/ENB2012_data.xlsx"]
        required += [out / name for name in ["run_metadata.json", "primary_results.csv", "shape_results.json", "shape_results.csv", "shape_fold_results.csv", "permutation_importance.csv", "design_demonstration.csv", "splits.csv", "selected_models.json"]]
        required += [out / "figures" / name for name in ["Y1_diagnostics.png", "Y2_diagnostics.png", "unseen_shape_errors.png"]]
        required += [ROOT / "models" / f"{target}_{method}_development.joblib" for target in ["Y1", "Y2"] for method in METHODS]
        if any(not path.is_file() for path in required):
            raise RuntimeError("Study artifacts are missing. Run ./setup.sh to prepare the six models before starting the app.")
        self.metadata = datasets.read_json(out / "run_metadata.json")
        if not self.metadata.get("completed"):
            raise RuntimeError("Study preparation did not finish. Run .venv/bin/python study.py, then restart.")
        for name, version in [("sklearn", sklearn.__version__), ("numpy", np.__version__), ("pandas", pd.__version__)]:
            if self.metadata[name] != version:
                raise RuntimeError(f"Model environment mismatch for {name}. Run ./setup.sh with the locked requirements.")
        self.df, self.groups, source = load_data(ROOT)
        if hashlib.sha256(source.read_bytes()).hexdigest() != self.metadata["data_sha256"]:
            raise RuntimeError("The dataset checksum differs from the completed study. Restore the original data or rerun study.py.")
        self.splits = pd.read_csv(out / "splits.csv").sort_values("row_id").reset_index(drop=True)
        if list(self.splits.row_id) != list(range(len(self.df))):
            raise RuntimeError("Study partition records do not match the dataset.")
        self.models = {
            (target, method): joblib.load(ROOT / "models" / f"{target}_{method}_development.joblib")
            for target in ["Y1", "Y2"] for method in METHODS
        }
        self.selected = datasets.read_json(out / "selected_models.json")

    def predict(self, features: pd.DataFrame):
        started = time.perf_counter()
        try:
            with threadpool_limits(limits=1):
                values = {key: model.predict(features[FEATURES]) for key, model in self.models.items()}
        except ValueError as exc:
            raise HTTPException(422, "The models could not interpret these values. Check numeric scale, input definitions, and category codes.") from exc
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        if any(not np.isfinite(value).all() for value in values.values()):
            raise HTTPException(422, "These values produced nonfinite predictions. Check input scale and units.")
        rows = [{"models": {method: {"heating": float(values["Y1", method][i]), "cooling": float(values["Y2", method][i])} for method in METHODS}} for i in range(len(features))]
        return rows, elapsed

    def catalog(self):
        frame = self.df[FEATURES].copy()
        frame.insert(0, "row_id", self.df.index)
        frame["shape_id"] = self.groups.astype(int)
        frame["partition"] = self.splits.partition
        shapes = []
        for group in sorted(set(self.groups)):
            item = self.df.loc[self.groups == group, FEATURES[:5]].iloc[0].to_dict()
            shapes.append({"id": int(group), "label": f"Shape {int(group) + 1:02}", **item})
        return {"records": datasets.records(frame), "shapes": shapes, "features": NAMES,
                "ranges": {key: {"min": float(self.df[key].min()), "max": float(self.df[key].max())} for key in FEATURES},
                "default_row_id": 2, "selected": self.selected}

    def results(self):
        out = ROOT / "results"
        tables = {key: datasets.records(pd.read_csv(out / filename)) for key, filename in {
            "primary": "primary_results.csv", "shape": "shape_results.csv", "folds": "shape_fold_results.csv",
            "importance": "permutation_importance.csv", "demonstration": "design_demonstration.csv",
        }.items()}
        return {**tables, "metadata": self.metadata, "selected": self.selected,
                "figures": ["/figures/Y1_diagnostics.png", "/figures/Y2_diagnostics.png", "/figures/unseen_shape_errors.png"]}


@asynccontextmanager
async def lifespan(application):
    application.state.study = Study()
    application.state.dataset_root = DATASET_ROOT
    DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Building Energy Lab", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS + ([PUBLIC_HOST] if PUBLIC_HOST else []))


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > datasets.MAX_BYTES + 65536:
                raise HTTPException(413, "The upload exceeds the 5 MiB file limit.")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(BodyLimit)


@app.middleware("http")
async def local_security(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ["GET", "HEAD", "OPTIONS"] and origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            parsed = None
        local_origin = parsed and parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS
        public_origin = PUBLIC_HOST and origin == f"https://{PUBLIC_HOST}"
        if not parsed or parsed.netloc != request.headers.get("host") or not (local_origin or public_origin):
            return JSONResponse({"detail": "Use the application from its current browser address."}, status_code=403)
    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > datasets.MAX_BYTES + 65536):
        return JSONResponse({"detail": "The request is too large. Choose a file up to 5 MiB."}, status_code=413)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_ids: list[Annotated[StrictInt, Field(ge=0, le=767)]] = Field(min_length=1, max_length=2)


class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, str] = Field(max_length=10)
    source_type: Literal["measurements", "simulation", "unknown"] = "unknown"
    response_units: str = Field(default="", max_length=160)
    response_definition: str = Field(default="", max_length=500)
    comparable: bool = False
    skip_invalid_rows: bool = False


@app.get("/")
def index():
    return FileResponse(APP_DIR / "static/index.html")


@app.get("/api/health")
def health():
    return {"status": "ready", "models": len(app.state.study.models), "offline": True, "shared": bool(PUBLIC_HOST)}


@app.get("/api/catalog")
def catalog():
    return app.state.study.catalog()


@app.post("/api/predict")
def predict(payload: PredictionRequest):
    study = app.state.study
    rows, elapsed = study.predict(study.df.loc[payload.row_ids, FEATURES])
    for row, row_id in zip(rows, payload.row_ids):
        row.update({"row_id": row_id, "partition": study.splits.loc[row_id, "partition"],
                    "features": {key: float(study.df.loc[row_id, key]) for key in FEATURES},
                    "reference": {"heating": float(study.df.loc[row_id, "Y1"]), "cooling": float(study.df.loc[row_id, "Y2"])}})
    return {"predictions": rows, "inference_ms": elapsed, "selected": study.selected}


@app.get("/api/results")
def results():
    return app.state.study.results()


@app.get("/api/datasets")
def dataset_list():
    return datasets.list_datasets(app.state.dataset_root)


@app.post("/api/datasets", status_code=201)
def upload(file: UploadFile):
    content = file.file.read(datasets.MAX_BYTES + 1)
    return datasets.inspect_upload(app.state.dataset_root, file.filename or "dataset", content)


@app.get("/api/datasets/{dataset_id}")
def dataset_details(dataset_id: str):
    return datasets.inspect_saved(app.state.dataset_root, dataset_id)


@app.post("/api/datasets/{dataset_id}/validate")
def validate_dataset(dataset_id: str, config: DatasetConfig):
    return datasets.validate(app.state.dataset_root, dataset_id, config.model_dump(), app.state.study)[-1]


@app.post("/api/datasets/{dataset_id}/evaluate")
def evaluate_dataset(dataset_id: str, config: DatasetConfig):
    return datasets.evaluate(app.state.dataset_root, dataset_id, config.model_dump(), app.state.study)


@app.get("/api/datasets/{dataset_id}/results")
def dataset_results(dataset_id: str):
    path = datasets.folder(app.state.dataset_root, dataset_id) / "results.json"
    if not path.is_file():
        raise HTTPException(404, "Evaluate this dataset first.")
    return datasets.read_json(path)


@app.get("/api/datasets/{dataset_id}/results.csv")
def dataset_csv(dataset_id: str):
    path = datasets.folder(app.state.dataset_root, dataset_id) / "results.csv"
    if not path.is_file():
        raise HTTPException(404, "Evaluate this dataset first.")
    return FileResponse(path, media_type="text/csv", filename=f"dataset-{dataset_id[:8]}-results.csv")


@app.get("/api/template/{kind}")
def template(kind: Literal["csv", "xlsx", "example"]):
    headers = FEATURES + ["Y1", "Y2"]
    example = app.state.study.df.loc[[2, 92, 332, 572], headers].copy() if kind == "example" else pd.DataFrame(columns=headers)
    if kind == "xlsx":
        buffer = io.BytesIO()
        example.to_excel(buffer, index=False, sheet_name="Building inputs")
        return Response(buffer.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="building-input-template.xlsx"'})
    return Response(example.to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="' + ("SIMULATED-demo-data.csv" if kind == "example" else "building-input-template.csv") + '"'})


app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.mount("/figures", StaticFiles(directory=ROOT / "results/figures", check_dir=False), name="figures")
