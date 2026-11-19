# Dynamic multi-project LAMP — design

Status: awaiting approval. Size: small-to-medium change. Date: 2026-11-19.

## Intent
Today one `.env` holds `DOCUMENT_ROOT`; switching project means editing it and
restarting everything. Fixed ports and `lamp-*` container names block running
two projects together. Goal: one command per project, same image, only the
folder changes, parallel, easy start/stop. Panel button comes later (non-goal now).

## Goals
- `lamp up <project>` / `lamp down <project>` / `lamp restart <project>`
- `lamp ls` (running projects + URLs), `lamp logs <project>`, `lamp shell <project>`, `lamp down-all`
- Projects run in parallel, each on its own host ports.
- ONE shared MySQL + phpMyAdmin. Starts when the first project goes up,
  stops when the last goes down. Each project uses its own database name inside it.
- Existing `./data/mysql` data stays untouched.

## Non-goals / anti-goals
- No reverse proxy, no `*.localhost` names (user chose ports).
- No per-project MySQL. No data migration.
- No Ubuntu top-bar button yet (next step; `lamp` CLI is its backend, `lamp ls --json` may come then).
- Must never stop `docker.service` / daemon (user rule). Never `restart: always`.

## Approaches considered
- A. Port per project (CHOSEN by user). Simple, no extra container. Trade-off: browsers share
  cookies across ports on `localhost`, so logins of two projects may overwrite each other.
  Accepted by user.
- B. Hostname per project via Caddy proxy. Cookie-isolated, clean 80/443. Extra container,
  hardcoded `localhost` URLs may break. Rejected by user.
- C. Both. More config. Rejected.

## Design
Files:
- `compose.shared.yml` — services `database`, `phpmyadmin`. Compose project `lamp-shared`.
  Creates network `lamp-net`. Database gets alias `database`, container `lamp-mysql8`.
  Ports as today: 127.0.0.1:3306, pma 8080/8443. `restart: "no"`.
- `compose.project.yml` — service `webserver` only. Joins external `lamp-net`. Compose project
  `lamp-<name>`, container `lamp-<name>`. Image tag `lamp-web:${PHPVERSION}` (built once per PHP version, not per project).
  Mounts: project dir -> `/var/www/html`, shared php.ini / ssl / vhosts, logs in `logs/<name>/`.
  DB host stays `database` (same name as today, so app configs keep working).
- `projects/<name>.env` — `PROJECT_DIR`, `PHPVERSION`, `HTTP_PORT`, `HTTPS_PORT`. Initial:
  - escrybe -> `./www-escrybe`, 8081 / 8481
  - lps-escrybe -> `./www-lps-escrybe`, 8082 / 8482
  - fazp -> `./www-fazp`, 8083 / 8483
  (builder verifies ports free first)
- Shared DB/credentials/pma/xdebug vars stay in existing `.env`.
- `lamp` bash script (repo root, symlinked to `~/.local/bin/lamp`):
  - `up`: run `dev-services-lease cancel`; start shared stack if not running; start project;
    run `dev-services-lease arm`; print URL.
  - `down`: stop project; if no other `lamp-*` web container running, stop shared stack.
  - `down-all`, `ls`, `logs`, `shell`, `restart`. Unknown project -> list valid ones.
  - Detects `docker compose` plugin vs `docker-compose` (like `dev_build_container.sh`).
  - Adding a project = drop a new `projects/x.env`. No YAML edits.
- Old `docker-compose.yml` replaced by the two files. `dev_build_container.sh` left as is (it targets old layout; noted in README).
- README gets a short "multi-project usage" section.

## Left to builder
- Exact `lamp-net` / healthcheck handling so web waits for MySQL ready.
- Uncommitted `bin/php83/Dockerfile` PUID change stays; keep it working.
- Test: bring up two projects together, confirm both answer on own ports, DB shared, last `down` stops MySQL.
