# Windows setup: Building Energy Lab

These instructions target Windows 10/11 on an Intel/AMD 64-bit computer, using PowerShell and Python 3.12. The repository includes all six trained model pipelines and the completed study. Internet is needed for the first installation; prepared inference works offline afterward.

## 1. Install Python 3.12

Download the **Python install manager** from [Python's Windows downloads page](https://www.python.org/downloads/windows/) and install it. Close and reopen PowerShell after installation.

Run:

```powershell
pymanager install 3.12
pymanager exec -V:3.12 --version
```

The second command should print `Python 3.12.x`. The project uses this version family to match its prepared models. The manager is documented in [Python's Windows guide](https://docs.python.org/3/using/windows.html#python-install-manager).

If Python 3.12 is already installed with the older Python launcher, `py -3.12 --version` can verify it. In that case, `py -3.12` can replace `pymanager exec -V:3.12` in these instructions.

## 2. Download and extract the project

1. Open [De1m0z/building-energy-lab](https://github.com/De1m0z/building-energy-lab).
2. Select **Code → Download ZIP**, or use this [source ZIP](https://github.com/De1m0z/building-energy-lab/archive/refs/heads/main.zip).
3. Right-click the downloaded ZIP and select **Extract All**.
4. Open the extracted folder that contains `app.py`, `requirements.txt`, and `energy_study`. There may be another folder inside the first extracted folder.
5. Click File Explorer's address bar, type `powershell`, and press **Enter**. This opens PowerShell in the project folder.

Confirm the current folder contains the app:

```powershell
Get-Item .\app.py, .\requirements.txt
```

If Git is already installed, cloning is an alternative to downloading the ZIP:

```powershell
git clone https://github.com/De1m0z/building-energy-lab.git
cd building-energy-lab
```

## 3. Create the environment and install packages

Run these commands one at a time from the project folder:

```powershell
pymanager exec -V:3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Wait for installation to finish successfully before continuing. All following commands use this environment's Python executable directly. Activation and PowerShell execution-policy changes are unnecessary. Python explains this approach in its [virtual-environment documentation](https://docs.python.org/3.12/library/venv.html#how-venvs-work).

Create the environment on the Windows computer itself. An environment copied from Linux or another computer is not portable.

## 4. Check the prepared models

```powershell
.\.venv\Scripts\python.exe -c "from app import Study; print('Models ready:', len(Study().models))"
```

Expected output:

```text
Models ready: 6
```

This checks model files, the original dataset checksum, and the core package versions. A complete download normally needs no retraining. If this check fails, resolve the reported error before starting the server.

## 5. Start the application

Run:

```powershell
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765 --workers 1
```

Leave this PowerShell window open. Wait for `Application startup complete`.

## 6. Open the app

Open Chrome or Edge and visit:

**http://127.0.0.1:8765**

The initial prediction should show heating **15.96** and cooling **22.40** for the default study record. You can use **Predict**, **Compare designs**, **Study results**, and **Test your dataset**.

To try dataset testing, select **Test your dataset → Try simulated example → Validate mapping → Run dataset test**. To upload your own file, follow the [dataset instructions](README.md#bring-your-own-building-data). Imported files and their latest results are saved in this Windows copy's `user_data` folder.

## Stop and start again

To stop the server, press **Ctrl+C** in its PowerShell window.

Next time, open PowerShell in the same project folder and repeat the commands in **step 5**, then open the browser address. Package installation and model preparation are not repeated on every launch.

## Common setup errors

| Problem | What to do |
|---|---|
| `pymanager` is not recognized | Install the Python install manager and reopen PowerShell. If Python 3.12 is already installed, check `py -3.12 --version` and use that launcher as described in step 1. |
| `app.py` or `requirements.txt` cannot be found | Open PowerShell inside the extracted folder containing those files. Run the `Get-Item` command in step 2 to check. |
| `.venv\Scripts\python.exe` cannot be found | The environment was not created in the current folder. Check step 2, then create it with the first command in step 3. |
| `No matching distribution found` | Confirm you are using Python 3.12 on Windows x64. Keep the pinned requirements; use the diagnostic command below. |
| The port is already in use / `WinError 10048` | Keep the existing app, or replace `--port 8765` with `--port 8766` in step 5 and open `http://127.0.0.1:8766`. |
| Missing artifacts or model-version mismatch | Extract the complete repository, including `energy_study`, and reinstall `requirements.txt` into the project's environment. Repeat step 4. |
| The browser cannot connect | Keep the server window open and check its error output. Open the exact address from step 6 after startup completes. |

Check the environment's Python version and architecture with:

```powershell
.\.venv\Scripts\python.exe -c "import sys, platform; print(sys.version); print(platform.machine())"
```

Optional API/data tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Verification limits

The pinned requirements and their conditional dependencies resolved successfully to prebuilt Windows x64 wheels for Python 3.12. The application tests pass on Linux. Installation, model loading, and browser operation have not yet been executed on a native Windows computer; this guide does not claim testing on Windows ARM64 or 32-bit Python.
