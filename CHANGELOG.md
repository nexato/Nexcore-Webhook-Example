# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-09-17

### Added

- `NEXCORE_ENV_FILE` points the service at its `.env` file by absolute path, for
  deployments where the working directory is decided by a service manager rather than by
  you. It takes precedence over the working directory and deliberately does *not* fall
  back to it: a wrong path reads as "not found" instead of quietly loading some other file
  that happens to be there.
- The service now records where its configuration came from. On startup it logs the file
  it loaded, or warns with every path it tried plus the settings that are still unset;
  previously, loading no `.env` at all left no trace anywhere.

### Changed

- `GET /healthz` reports configuration state next to liveness: `version`,
  `config_source`, `configured`, and `missing` listing the names of unset environment
  variables (names only, never values). The existing `"status": "ok"` field is unchanged,
  so probes that check it keep working — a probe comparing the entire response body needs
  updating.
- The Windows deployment guide sets `NEXCORE_ENV_FILE` when registering the NSSM service,
  notes that the commands belong in `cmd.exe` (`^` is not PowerShell's line-continuation
  character, which silently splits the command apart), and gained a triage section for
  settings that appear to be ignored.
- The Cloudflare Tunnel guide now states the domain requirement the tunnel stands on,
  instead of mentioning it in passing: either a domain registered with Cloudflare, or your
  own domain delegated to Cloudflare's nameservers. Includes the DNSSEC and DNS-record
  pitfalls of that switch, that the delegation covers the whole zone rather than just the
  webhook hostname, and which cheaper-looking alternatives are gated behind paid plans.

### Fixed

- The `.env` file was located relative to the process working directory, so a service
  started from anywhere else silently ran on the built-in defaults — no error, and
  `/healthz` still answered `ok`. Windows installations were hit hardest, because NSSM
  defaults the working directory to the directory holding the executable
  (`.venv\Scripts`), leaving no choice but to repeat every setting through
  `nssm set … AppEnvironmentExtra`. Configuration is now found by absolute path.
  Linux/systemd and Docker deployments were never affected: both hand the settings to the
  process as real environment variables.

## [1.1.0] - 2026-08-31

### Added

- Order exports can now be named after the order number instead of the entity UUID.
  For `export.completed` events whose `data.sourceEvent` is `rental.order.completed`,
  the service looks the order up via `GET /api/v1/order/{entityId}` and stores the file
  as `<orderNumber>_<YYYYMMDDTHHMMSS>.<ext>`. Enabled by default and controlled by the
  new `ORDER_NUMBER_FILENAMES` setting; any lookup problem falls back to the previous
  `<entityId>_<index>.<ext>` naming, so a file is never lost. The lookup runs after the
  webhook has been acknowledged and does not affect response time.
- `CHANGELOG.md` — this file.

### Changed

- The application version is now read from the package metadata instead of being
  hardcoded, making `pyproject.toml` the single source of truth. Releases 1.0.0–1.0.6
  shipped while the declared version stayed at `0.1.0`.
- Releases are now prepared with `ci/prepare_release.py`, which bumps the version and
  scaffolds the changelog section, and the release process is documented end to end.

### Fixed

- Documentation referred to "the 8 supported events" while only five are listed; the
  three `operatedRental.*` events were removed from the table in 1.0.6.
- `.env.example` described the nexcore API credentials as being used by the
  `subscription` CLI only. The running service now uses them too, for the order lookup.

## [1.0.6] - 2026-07-10

### Changed

- Removed event types that are not available, and added a link to the support center.

## [1.0.1] - [1.0.5] - 2026-07-06 – 2026-07-07

### Added

- `CONTRIBUTING.md`, `SECURITY.md` and `NOTICE.md`.

### Fixed

- Documentation corrections: LICENSE link, wording of the Power Automate low-code
  receiver, capitalization and README formatting.

## [1.0.0] - 2026-07-06

### Added

- Initial public release: a standalone FastAPI service that receives nexcore
  `export.completed` webhooks and downloads the exported PDF/ZIP files into a directory.
- HMAC signature verification over the raw request body.
- File downloader for pre-signed Azure SAS URLs, with retries, a size cap and
  path-traversal hardening.
- Idempotency and subscription state in a local SQLite file.
- Subscription self-management CLI (`register`, `status`, `delete`, `rotate-secret`).
- Deployment guides for Docker/Compose, Linux (systemd) and Windows, plus Caddy and
  Cloudflare Tunnel ingress examples.
- Self-test script that sends a correctly signed sample webhook without needing nexcore.
