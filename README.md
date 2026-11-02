# Building Energy Lab

A local application for Group 3’s CPE127 architectural energy study. It runs actual scikit-learn predictions, compares study designs, explains the completed experiment, and tests uploaded building datasets.

Authors: Frizza Mae G. Cale, Julea Kriszel M. Guzman, and Annika Ruzzette A. Lomugdang.

## Start here

Use Python 3.12 on Linux with its `venv` module. Clone the repository and install the locked environment:

```bash
git clone https://github.com/De1m0z/building-energy-lab.git
cd building-energy-lab
./setup.sh
./run.sh
```

The six trained pipelines and completed study are included. After the first setup, start the app with `./run.sh`.

Open **http://127.0.0.1:8765**. Stop the server with **Ctrl+C** in its terminal. If the port is occupied, keep the existing app or choose a different port:

```bash
PORT=8766 ./run.sh
```

The prepared application runs offline. It binds only to this computer, not the local network.

The interface includes short view and result transitions, button feedback, and a glazing preview that responds to your selection. Motion uses native browser features and stops for keyboard interaction or the system’s reduced-motion setting. Prediction values are displayed directly; they are not animated through invented intermediate values.

## Temporary online access

A Cloudflare Quick Tunnel can share this app while this computer and the tunnel process stay online. Set `ENERGY_PUBLIC_HOST` to the exact generated hostname (for example, `example.trycloudflare.com`) before starting the sharing instance. This allows that HTTPS origin through the host and same-origin checks; local-only access remains the default.

The demonstration tunnel on the original development computer saves its URL and process IDs in `.cache/tunnel/state.json`; its logs are in the same folder. That sharing instance uses a separate dataset folder at `.cache/tunnel/datasets`, so online visitors do not see imports from the local `user_data/` library. These machine-specific files are excluded from Git. All visitors to a public sharing instance share its dataset library. Stop the tunnel process to revoke the link. The hostname changes when a new Quick Tunnel is created. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

Optional environment variables are `PORT` (default `8765`) and `ENERGY_PUBLIC_HOST` (empty by default). Set them in the shell when launching the app. `.env.example` lists the keys for reference; the scripts do not automatically load `.env` files.

## First installation on another Linux computer

Use Python 3.12 with its `venv` module and internet access for the initial dependency installation:

```bash
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

`setup.sh` creates an isolated environment, installs the exact versions in `requirements.txt`, and checks that the study bundle can load. The submission includes prepared artifacts, so it normally does not need to retrain. Missing artifacts trigger the study preparation, which downloads the UCI spreadsheet if needed and can take several minutes. No GPU or API key is required. Internet is not needed for subsequent launches.

## Four workspaces

**Predict:** Choose a valid shape, orientation, and glazing configuration. Geometry is derived from the recorded shape. All three models predict separate heating and cooling loads. Random Forest is highlighted because it was selected by development cross-validation. The initial example is held-out record 2. Reference values are explicitly labeled as simulated.

**Compare designs:** Compare two valid study records. The table and CSV show each model’s predictions and **B minus A** differences. These predictions use the development-trained models. The matched example in Study Results instead uses saved predictions from models that excluded the entire shape.

**Study results:** Inspect both evaluation protocols, the mean baseline, feature importance, timing, residual plots, and the glazing example. Results come from the completed local run, not hardcoded paper scores. A small table compares the four headline paper MAEs with this run at the reported precision.

**Test your dataset:** Drop or choose a CSV/XLSX file, review column mappings, validate records, and test the frozen study models. A three-step guide shows progress. Required building inputs are separated from optional reference loads, and a one-click simulated example demonstrates the import flow. This workflow evaluates existing models; it never retrains them or alters the benchmark.

## Bring your own building data

1. Open **Test your dataset** and download a CSV or Excel template.
2. Supply the eight inputs below. Descriptive column names can be mapped after upload.
3. Optionally supply one or both reference loads, Y1 and Y2.
4. Upload the file, review its first 20 records and detected source types, then map the columns.
5. Select the data source and, if scoring references, record the response units and measurement definition. Confirm comparability only after checking it yourself.
6. Select **Validate mapping**, review errors and domain notices, then **Run dataset test**.
7. Download the row-level CSV or complete JSON report. Reopen the latest evaluation from the local library later.

| Input | Meaning and convention |
|---|---|
| X1 | Relative compactness: the source’s dimensionless geometric metric; positive and at most 1. Use the same definition, not an unrelated compactness ratio. |
| X2 | Surface area, using the benchmark’s geometric scale and definition. |
| X3 | Wall area, using the same scale and definition. |
| X4 | Roof area, using the same scale and definition. |
| X5 | Overall height, using the same scale and definition. |
| X6 | Source orientation category: 2, 3, 4, or 5. The app preserves codes rather than guessing a direction mapping. |
| X7 | Glazing as a fraction of floor area: 0.25 means 25%, not 25. Study levels are 0, 0.10, 0.25, and 0.40. Other valid fractions receive domain notices where appropriate. |
| X8 | 0: no glazing; 1: uniform distribution; 2: north emphasis; 3: east emphasis; 4: south emphasis; 5: west emphasis. Zero glazing requires code 0; positive glazing requires 1–5. |
| Y1, Y2 | Optional reference heating and cooling loads. These never enter the prediction features. |

The geometric building scale comes from the original study’s 3.5-m elementary cubes; measured geometric values must be converted to compatible definitions before import. No automatic unit conversion is performed. The repository leaves response units unspecified, so the interface uses **original dataset load units**, not an assumed kWh or electricity-bill interpretation. A unit declaration alone does not prove that measured energy consumption and a simulated load response are comparable.

Upload limits: **5 MiB, 10,000 data rows, 64 columns**. CSV must be UTF-8 (a UTF-8 BOM is accepted). The first row must contain unique, nonempty headers. Excel uses the **first worksheet**. Formulas are not executed; only cached cell values are read, and absent cached values fail validation. Expanded XLSX contents are limited to 50 MiB.

Invalid input records require correction or explicit permission to evaluate valid rows only. Rejected records remain in the CSV. Blank rows are counted and excluded; repeated input configurations are retained with notices. Unsupported category codes are rejected. Physically plausible but unfamiliar geometry can be predicted and is flagged as outside the studied shapes.

Without compatible reference loads, the app provides **predictions only**. With a comparability declaration and usable references, it calculates MAE, RMSE, and R² per target and model, with sample counts. R² is unavailable with fewer than two references or constant references. Partial reference coverage excludes only those missing/invalid references from that target’s metrics, not from prediction. R² is never labeled percentage accuracy.

The downloadable simulated example contains original benchmark records and is named `SIMULATED-demo-data.csv`. It is a workflow demonstration, not independent real-world validation. Matches to development/test input configurations are disclosed in uploaded-data reports.

## Files, persistence, and privacy

`study.py` contains the notebook’s original 169-line training cell, with its output location adapted to this folder and an executable entry point appended. `research/FINAL-Building_Energy_Study.ipynb` preserves the notebook content. `research/reproduction.json` records the local reproduction and headline paper comparisons.

`energy_study/` contains the original data, six fitted pipelines, splits, search results, predictions, metrics, metadata, and figures. `user_data/` contains locally imported files, their checksums and mappings, and the latest CSV/JSON evaluation for each import. User imports are never mounted as public static files. Changed originals must be imported again; the library checks their hashes.

There is no account, telemetry, cloud storage, or external inference service. Source links in Study Results need internet only when you deliberately open them. Treat model files as trusted executable artifacts: the app accepts data files, not user-provided serialized models.

`Building_Energy_Lab_Submission.zip` includes source, the locked dependencies, original notebook, prepared study artifacts, tests, research notes, and this guide. It excludes the virtual environment, caches, verification downloads, and all uploaded user datasets.

## Reproduce and verify

Rerun the complete study explicitly, with the server stopped:

```bash
.venv/bin/python study.py
```

This regenerates study results and model artifacts. The experiment uses seed 42, an 80/20 development/test split, five-fold development CV, and nested leave-one-shape-out evaluation with three inner grouped folds. The locally reproduced headline MAEs match the paper: RF holdout **0.356 / 1.202** and MLR unseen-shape **3.473 / 3.926**, for heating/cooling. Runtime values are measured on this computer and differ from the paper’s host-specific values.

Run the API/data checks:

```bash
.venv/bin/python -m pytest -q
```

For browser checks, install Google Chrome (the current computer already has it), start a temporary copy of the app on port 8797 with a temporary dataset folder, and run:

```bash
.venv/bin/python -c 'import app, tempfile, uvicorn; from pathlib import Path; app.DATASET_ROOT = Path(tempfile.mkdtemp(prefix="energy-browser-")); uvicorn.run(app.app, host="127.0.0.1", port=8797)'
```

Leave that terminal open. In a second terminal in the same folder:

```bash
.venv/bin/python tests/browser_check.py http://127.0.0.1:8797
```

The browser check creates only simulated test imports on its test server. Use a separate server to avoid populating your own dataset library. An optional second argument is a local `axe.min.js` file for WCAG automated checks. The recorded verification used the installed webapp-testing server helper, an isolated data folder, and axe-core. Screenshots and the result summary are in `verification/` on this computer.

The current Starlette test client emits a deprecation warning for HTTPX; this does not affect serving or test results.

## Troubleshooting

- **Engine unavailable:** confirm `./run.sh` is running, then reload the page.
- **Missing study artifacts or environment mismatch:** run `./setup.sh` and restart. Do not replace trained pipelines with files from another scikit-learn version.
- **Changed dataset checksum:** restore the original UCI spreadsheet from the submission or source, then rerun the study if you intentionally changed the experiment.
- **Upload errors:** use a template, keep data on the first Excel sheet, use fractions for X7, and correct invalid rows or explicitly opt into valid rows only.
- **No reference scores:** supply mapped Y1/Y2 references, units, measurement definitions, and comparability confirmation. Predictions can run without reference scores.

## Sources and limits

[UCI Energy Efficiency dataset](https://archive.ics.uci.edu/dataset/242/energy%2Befficiency), Tsanas & Xifara (2012), DOI [10.24432/C51307](https://doi.org/10.24432/C51307), CC BY 4.0. Original research: [Accurate quantitative estimation of energy performance of residential buildings using statistical machine learning tools](https://doi.org/10.1016/j.enbuild.2012.03.003).

This is a simulated benchmark demonstration and a bounded external-data testing tool. It has no Philippine field validation and does not establish real-building energy savings, code compliance, or superiority to a detailed energy simulator. Full arbitrary-schema training, deployment, account management, and changes to the submitted paper are outside this application.
