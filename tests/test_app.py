import hashlib
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline

import app as server
import datasets


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATASET_ROOT", tmp_path / "imports")
    with TestClient(server.app) as connection:
        yield connection


def sample():
    return server.app.state.study.df.loc[[2, 92, 332, 572]].reset_index(drop=True).copy()


def upload(client, frame, filename="study-sample.csv"):
    response = client.post("/api/datasets", files={"file": (filename, frame.to_csv(index=False).encode(), "text/csv")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def config(columns=None, **changes):
    result = {"mapping": {key: key for key in (columns or datasets.FEATURES)}, "source_type": "simulation",
              "response_units": "original dataset load units", "response_definition": "UCI Energy Efficiency simulated Y1/Y2", "comparable": False, "skip_invalid_rows": False}
    result.update(changes)
    return result


def test_readiness_and_real_predictions(client, monkeypatch):
    assert client.get("/api/health").json()["models"] == 6
    assert client.get("/api/health").json()["shared"] is False
    def no_fit(*args, **kwargs):
        raise AssertionError("Serving or external evaluation must never fit models")
    monkeypatch.setattr(Pipeline, "fit", no_fit)
    response = client.post("/api/predict", json={"row_ids": [2]})
    assert response.status_code == 200
    record = response.json()["predictions"][0]
    assert record["partition"] == "test"
    assert record["reference"] == {"heating": 15.55, "cooling": 21.33}
    assert record["models"]["RF"]["heating"] == pytest.approx(15.964, abs=.001)
    assert record["models"]["RF"]["cooling"] == pytest.approx(22.398, abs=.001)
    assert set(record["features"]) == set(datasets.FEATURES)
    assert response.json()["inference_ms"] < 1000
    dataset_id = upload(client, sample())
    assert client.post(f"/api/datasets/{dataset_id}/evaluate", json=config()).status_code == 200


@pytest.mark.parametrize("row_ids", [[], [True], ["2"], [-1], [768], [0, 1, 2]])
def test_prediction_request_boundaries(client, row_ids):
    assert client.post("/api/predict", json={"row_ids": row_ids}).status_code == 422


def test_comparison_and_catalog(client):
    catalog = client.get("/api/catalog").json()
    assert len(catalog["records"]) == 768 and len(catalog["shapes"]) == 12
    assert sum(row["partition"] == "test" for row in catalog["records"]) == 154
    for row in catalog["records"]:
        assert (row["X7"] == 0) == (row["X8"] == 0)
    result = client.post("/api/predict", json={"row_ids": [332, 332]}).json()
    assert result["predictions"][0] == result["predictions"][1]


def test_benchmark_metrics_and_fold_coverage(client):
    result = client.get("/api/results").json()
    assert len(result["primary"]) == 8 and len(result["shape"]) == 6 and len(result["folds"]) == 72
    out = server.ROOT / "results"
    predictions = pd.read_csv(out / "test_predictions.csv")
    for row in result["primary"]:
        if row["model"] == "Mean baseline":
            continue
        group = predictions[(predictions.target == row["target"]) & (predictions.model == row["model"])]
        assert len(group) == 154
        assert mean_absolute_error(group.actual, group.predicted) == pytest.approx(row["MAE"])
        assert np.sqrt(mean_squared_error(group.actual, group.predicted)) == pytest.approx(row["RMSE"])
        assert r2_score(group.actual, group.predicted) == pytest.approx(row["R2"])
    grouped = pd.read_csv(out / "shape_predictions.csv")
    assert grouped.groupby(["target", "model"]).row_id.nunique().eq(768).all()
    study = server.app.state.study
    for group in set(study.groups):
        assert not set(study.groups[study.groups == group]) & set(study.groups[study.groups != group])
    assert result["metadata"]["data_sha256"] == hashlib.sha256((server.ROOT / "data/ENB2012_data.xlsx").read_bytes()).hexdigest()


def test_mapped_batch_scoring_and_local_persistence(client):
    frame = sample().rename(columns={key: "source_" + key for key in datasets.FEATURES + datasets.TARGETS})
    dataset_id = upload(client, frame, "../../my-building.csv")
    mapping = {key: "source_" + key for key in datasets.FEATURES + datasets.TARGETS}
    settings = config(mapping=mapping, comparable=True)
    validation = client.post(f"/api/datasets/{dataset_id}/validate", json=settings)
    assert validation.status_code == 200 and validation.json()["valid_rows"] == 4
    result = client.post(f"/api/datasets/{dataset_id}/evaluate", json=settings)
    assert result.status_code == 200, result.text
    report = result.json()
    assert len(report["metrics"]) == 6
    expected = server.app.state.study.models["Y1", "RF"].predict(sample()[datasets.FEATURES])
    assert [row["RF_Y1_predicted"] for row in report["rows"]] == pytest.approx(expected)
    rf = next(row for row in report["metrics"] if row["model"] == "RF" and row["target"] == "Y1")
    assert rf["MAE"] == pytest.approx(mean_absolute_error(sample().Y1, expected))
    saved = client.get(f"/api/datasets/{dataset_id}").json()
    assert saved["name"] == "my-building.csv" and saved["config"]["mapping"] == mapping
    assert client.get(f"/api/datasets/{dataset_id}/results").json() == report
    listing = client.get("/api/datasets").json()
    assert listing[0]["has_results"]
    exported = client.get(f"/api/datasets/{dataset_id}/results.csv")
    assert len(pd.read_csv(io.StringIO(exported.text))) == 4
    assert client.get(f"/user_data/{dataset_id}/source.csv").status_code == 404


def test_invalid_rows_require_explicit_choice(client):
    frame = sample()
    frame.loc[0, "X6"] = 99
    frame.loc[1, "X2"] = -1
    dataset_id = upload(client, frame)
    settings = config()
    report = client.post(f"/api/datasets/{dataset_id}/validate", json=settings).json()
    assert report["valid_rows"] == 2 and report["invalid_rows"] == 2
    assert client.post(f"/api/datasets/{dataset_id}/evaluate", json=settings).status_code == 422
    report = client.post(f"/api/datasets/{dataset_id}/evaluate", json={**settings, "skip_invalid_rows": True}).json()
    assert report["rows"][0]["status"] == "rejected" and report["rows"][0]["RF_Y1_predicted"] is None
    assert len(report["rows"]) == 4 and report["valid_rows"] == 2


def test_prediction_only_and_comparability_gate(client):
    dataset_id = upload(client, sample())
    settings = config(datasets.FEATURES + datasets.TARGETS)
    assert client.post(f"/api/datasets/{dataset_id}/evaluate", json=settings).json()["metrics"] == []
    assert client.post(f"/api/datasets/{dataset_id}/evaluate", json={**settings, "comparable": True, "response_units": ""}).json()["metrics"] == []
    dataset_id = upload(client, sample().drop(columns=datasets.TARGETS))
    assert client.post(f"/api/datasets/{dataset_id}/evaluate", json=config(comparable=True)).json()["metrics"] == []


@pytest.mark.parametrize("constant, count", [(True, 4), (False, 1)])
def test_undefined_r2_and_partial_reference_coverage(client, constant, count):
    frame = sample().head(count)
    if constant:
        frame["Y1"] = 10
        frame.loc[0, "Y2"] = np.nan
    dataset_id = upload(client, frame)
    report = client.post(f"/api/datasets/{dataset_id}/evaluate", json=config(datasets.FEATURES + datasets.TARGETS, comparable=True)).json()
    assert all(row["R2"] is None for row in report["metrics"] if row["target"] == "Y1")
    assert report["reference_counts"]["Y2"] == (3 if constant else 1)
    assert len(report["rows"]) == count


def test_duplicates_and_outside_geometry_are_reported_not_silently_dropped(client):
    frame = pd.concat([sample().iloc[[0]], sample().iloc[[0]]], ignore_index=True)
    frame["X5"] = 8
    dataset_id = upload(client, frame)
    report = client.post(f"/api/datasets/{dataset_id}/evaluate", json=config()).json()
    assert report["valid_rows"] == 2 and report["duplicate_rows"] == 2
    assert "outside benchmark range" in report["rows"][0]["issues"]
    assert "Geometry absent" in report["rows"][0]["issues"]


def test_missing_or_shared_columns_are_rejected(client):
    dataset_id = upload(client, sample())
    assert client.post(f"/api/datasets/{dataset_id}/validate", json=config(["X1"])).status_code == 422
    settings = config()
    settings["mapping"]["X2"] = "X1"
    assert client.post(f"/api/datasets/{dataset_id}/validate", json=settings).status_code == 422


def test_extreme_numeric_values_do_not_crash_models_or_metrics(client):
    frame = sample()
    frame.loc[0, "X2"] = 1e100
    frame.loc[1, "Y1"] = 1e200
    dataset_id = upload(client, frame)
    report = client.post(f"/api/datasets/{dataset_id}/evaluate", json=config(datasets.FEATURES + datasets.TARGETS, comparable=True, skip_invalid_rows=True))
    assert report.status_code == 200, report.text
    assert report.json()["invalid_rows"] == 1
    assert report.json()["reference_counts"]["Y1"] == 2


def test_excel_import_and_templates(client):
    workbook = io.BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        sample().to_excel(writer, index=False, sheet_name="Measurements")
        pd.DataFrame({"not_the_data": [1]}).to_excel(writer, index=False, sheet_name="Ignored sheet")
    response = client.post("/api/datasets", files={"file": ("building.xlsx", workbook.getvalue())})
    assert response.status_code == 201, response.text
    assert response.json()["sheet"] == "Measurements" and response.json()["rows"] == 4
    dataset_id = response.json()["id"]
    assert client.post(f"/api/datasets/{dataset_id}/evaluate", json=config()).status_code == 200
    template = client.get("/api/template/xlsx")
    assert list(pd.read_excel(io.BytesIO(template.content)).columns) == datasets.FEATURES + datasets.TARGETS
    assert client.get("/api/template/example").headers["content-disposition"].find("SIMULATED") >= 0


@pytest.mark.parametrize("filename, content, status", [("bad.csv", b"X1,X1\n1,2\n", 400), ("bad.xlsx", b"not an excel file", 400), ("model.joblib", b"not allowed", 400), ("empty.csv", b"", 413), ("wide.csv", (",".join(f"a{i}" for i in range(65)) + "\n1\n").encode(), 400), ("large.csv", b"a" * (datasets.MAX_BYTES + 1), 413)])
def test_upload_boundaries(client, filename, content, status):
    assert client.post("/api/datasets", files={"file": (filename, content)}).status_code == status


def test_expanded_workbook_limit(client):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("xl/workbook.xml", b"x" * (50 * 1024 * 1024 + 1))
    assert client.post("/api/datasets", files={"file": ("expanded.xlsx", archive.getvalue())}).status_code == 400


def test_local_origin_and_host_protection(client):
    assert client.post("/api/predict", json={"row_ids": [2]}, headers={"Origin": "https://outside.example"}).status_code == 403
    assert client.post("/api/predict", json={"row_ids": [2]}, headers={"Origin": "https://testserver"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "outside.example"}).status_code == 400
    assert client.get("/api/datasets/not-a-storage-id").status_code == 404
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]


def test_public_origin_is_explicit_and_same_host(client, monkeypatch):
    monkeypatch.setattr(server, "PUBLIC_HOST", "testserver")
    assert client.get("/api/health").json()["shared"] is True
    assert client.post("/api/predict", json={"row_ids": [2]}, headers={"Origin": "https://testserver"}).status_code == 200
    for origin in ["https://outside.example", "https://testserver.outside.example", "https://testserver:443", "https://[", "null"]:
        assert client.post("/api/predict", json={"row_ids": [2]}, headers={"Origin": origin}).status_code == 403
    assert client.post("/api/predict", json={"row_ids": [2]}, headers={"Origin": "https://testserver", "Host": "localhost"}).status_code == 403
    assert client.post("/api/predict", json={"row_ids": [2]}, headers={"Origin": "http://testserver"}).status_code == 200


def test_original_import_integrity_and_types(client):
    dataset_id = upload(client, sample())
    detail = client.get(f"/api/datasets/{dataset_id}").json()
    assert detail["types"]["X1"] == "numeric"
    path = server.app.state.dataset_root / dataset_id / "source.csv"
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    assert client.post(f"/api/datasets/{dataset_id}/validate", json=config()).status_code == 409
    path.unlink()
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 410

