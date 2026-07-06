# Windows service registration

Two ways to run the receiver as a Windows service. **NSSM is recommended** (simplest, robust
logging and restart handling). No custom service-wrapper code is needed.

Assumptions:

- Python 3.11+ installed
- The project is at `C:\nexcore-webhook-example` with a virtualenv at `.venv` and the app
  installed (`python -m venv .venv` → `.venv\Scripts\pip install .`)
- `C:\nexcore-webhook-example\.env` filled in from `.env.example`

## Option A — NSSM (recommended)

[NSSM](https://nssm.cc/) supervises the process and restarts it on failure.

```bat
nssm install NexcoreWebhook "C:\nexcore-webhook-example\.venv\Scripts\python.exe" ^
    "-m" "uvicorn" "app.main:app" "--host" "0.0.0.0" "--port" "8000"
nssm set NexcoreWebhook AppDirectory "C:\nexcore-webhook-example"
nssm set NexcoreWebhook AppStdout "C:\nexcore-webhook-example\logs\service.log"
nssm set NexcoreWebhook AppStderr "C:\nexcore-webhook-example\logs\service.log"
nssm set NexcoreWebhook Start SERVICE_AUTO_START
nssm start NexcoreWebhook
```

`AppDirectory` makes the service load `.env` and write `OUTPUT_DIR` / `STATE_DB_PATH` relative
to the project folder. To pass configuration, either keep the `.env` file in `AppDirectory` or
set variables with `nssm set NexcoreWebhook AppEnvironmentExtra KEY=VALUE`.

Manage it:

```bat
nssm restart NexcoreWebhook
nssm stop NexcoreWebhook
nssm remove NexcoreWebhook confirm
```

## Option B — sc.exe (built-in)

`sc.exe` has no process supervisor, so use a small launcher batch file as the service binary.

`C:\nexcore-webhook-example\run-service.bat`:

```bat
@echo off
cd /d C:\nexcore-webhook-example
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Register and start:

```bat
sc.exe create NexcoreWebhook binPath= "C:\nexcore-webhook-example\run-service.bat" start= auto
sc.exe start NexcoreWebhook
sc.exe query NexcoreWebhook
```

> Note the required spaces after `binPath=` and `start=`. `sc.exe` won't restart a crashed
> process automatically (configure recovery with `sc.exe failure NexcoreWebhook ...` or prefer
> NSSM).

## Verify

```bat
curl http://localhost:8000/healthz
```

See [../../docs/deployment-windows.md](../../docs/deployment-windows.md) for the full walkthrough.
