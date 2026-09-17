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

Run these in **cmd.exe**, not PowerShell — `^` is cmd's line-continuation character and
PowerShell will break the command apart.

```bat
nssm install nexcoreWebhook "C:\nexcore-webhook-example\.venv\Scripts\python.exe" ^
    "-m" "uvicorn" "app.main:app" "--host" "0.0.0.0" "--port" "8000"
nssm set nexcoreWebhook AppDirectory "C:\nexcore-webhook-example"
nssm set nexcoreWebhook AppEnvironmentExtra NEXCORE_ENV_FILE=C:\nexcore-webhook-example\.env
nssm set nexcoreWebhook AppStdout "C:\nexcore-webhook-example\logs\service.log"
nssm set nexcoreWebhook AppStderr "C:\nexcore-webhook-example\logs\service.log"
nssm set nexcoreWebhook Start SERVICE_AUTO_START
nssm start nexcoreWebhook
```

`AppDirectory` sets the service's working directory, which is where relative `OUTPUT_DIR` /
`STATE_DB_PATH` values land. `NEXCORE_ENV_FILE` points at the `.env` file by absolute path, so
configuration is found regardless of the working directory — set it and the two cannot drift
apart. Individual settings can still be passed directly:
`nssm set nexcoreWebhook AppEnvironmentExtra KEY=VALUE` (one call, space-separated for several).

Manage it:

```bat
nssm restart nexcoreWebhook
nssm stop nexcoreWebhook
nssm remove nexcoreWebhook confirm
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
sc.exe create nexcoreWebhook binPath= "C:\nexcore-webhook-example\run-service.bat" start= auto
sc.exe start nexcoreWebhook
sc.exe query nexcoreWebhook
```

> Note the required spaces after `binPath=` and `start=`. `sc.exe` won't restart a crashed
> process automatically (configure recovery with `sc.exe failure nexcoreWebhook ...` or prefer
> NSSM).

## Verify

```bat
curl http://localhost:8000/healthz
```

Check `configured` in the response, not just the status code:

```json
{"status":"ok","version":"1.1.0","config_source":"C:\\nexcore-webhook-example\\.env",
 "configured":true,"missing":[]}
```

`"config_source":"environment only"` means no `.env` was found — the service is running on
defaults. The startup lines in `logs\service.log` say which paths were tried.

## If settings are ignored

The service starts and answers `/healthz` even with no configuration at all, so "it runs" is not
evidence that `.env` was read. Work down this list:

```bat
nssm get nexcoreWebhook AppDirectory
nssm get nexcoreWebhook AppEnvironmentExtra
nssm get nexcoreWebhook ObjectName
dir /a C:\nexcore-webhook-example\.env*
```

- **`dir` shows `.env.txt`** — Notepad appended the extension while "hide known file types" was
  on. Rename it.
- **`AppDirectory` looks truncated or has a stray quote** — a trailing backslash before the
  closing quote (`"C:\nexcore-webhook-example\"`) is escaped by cmd. Set it without one.
- **`ObjectName` is a dedicated account** — NSSM's default is `LocalSystem`; a custom account may
  not be able to read the file. Check its permissions on the project folder.
- **Nothing obvious** — set `NEXCORE_ENV_FILE` to the absolute path as shown above and restart.
  It removes the working directory from the equation entirely.

See [../../docs/deployment-windows.md](../../docs/deployment-windows.md) for the full walkthrough.
