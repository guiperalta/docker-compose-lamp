# Dynamic Multi-Project LAMP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `lamp up|down <project>` runs any project folder on the same image, in parallel, with one shared MySQL that auto starts/stops.

**Architecture:** Two compose files. `compose.shared.yml` (database + phpMyAdmin, project `lamp-shared`, network `lamp-net`). `compose.project.yml` (webserver only, project `lamp-<name>`, external `lamp-net`). A `lamp` bash script picks per-project values from `projects/<name>.env` and orchestrates both.

**Tech Stack:** Docker Compose (plugin or standalone), bash.

**Spec:** `docs/superpowers/specs/2026-11-19-dynamic-projects-design.md`

## Global Constraints

- Never stop/disable `docker.service`, `containerd.service`, `docker.socket`.
- Never `restart: always` / `unless-stopped`. Use `restart: "no"`.
- Before using dev services: `/home/peralta/.local/bin/dev-services-lease cancel`. After starting: `/home/peralta/.local/bin/dev-services-lease arm`.
- Existing `./data/mysql` untouched. DB host name for apps stays `database`.
- Ports: escrybe 8081/8481, lps-escrybe 8082/8482, fazp 8083/8483; pma 8080/8443; MySQL 127.0.0.1:3306.
- Compose `--env-file` REPLACES the default `.env`. Always pass `--env-file .env --env-file projects/<name>.env` (later wins).
- Support `docker compose` plugin, fallback `docker-compose` (same detection as `dev_build_container.sh`).
- Commit messages end with the attribution lines from the session reminder.

## Review Focus

- `lamp up x` twice: second call is a no-op/restart, no error, no duplicate containers.
- `lamp down x` while another project runs: MySQL must stay up.
- Project name not in `projects/`: print valid names, exit non-zero, start nothing.
- Port already in use on host: compose error is surfaced, shared stack not left running if no project is up.
- Project dir missing on disk: refuse before starting anything.

---

### Task 1: Compose split + project env files

**Files:**
- Create: `compose.shared.yml`, `compose.project.yml`, `projects/escrybe.env`, `projects/lps-escrybe.env`, `projects/fazp.env`
- Delete (git rm): `docker-compose.yml`
- Modify: `.gitignore` only if it ignores `projects/` (check; it must not)

**Interfaces:**
- Produces: env vars per project file: `PROJECT_NAME`, `PROJECT_DIR`, `PHPVERSION`, `HTTP_PORT`, `HTTPS_PORT`. Network name `lamp-net`. Image tag `lamp-web:${PHPVERSION}`. Shared DB container `lamp-${DATABASE}`; shared compose project name `lamp-shared`; web container `lamp-${PROJECT_NAME}`.

- [ ] **Step 1: Write `projects/*.env`** with the three projects and ports from Global Constraints (`PROJECT_DIR=./www-escrybe`, etc., `PHPVERSION=php83`).
- [ ] **Step 2: Write `compose.shared.yml`** — `database` (build `./bin/${DATABASE}`, container `lamp-${DATABASE}`, same volumes/ports/env as old file, plus healthcheck `mysqladmin ping -h localhost -uroot -p$$MYSQL_ROOT_PASSWORD`) and `phpmyadmin` (same as old, `depends_on` database healthy, host `database`). Network `lamp-net` with `name: lamp-net`. `restart: "no"`. No `links`.
- [ ] **Step 3: Write `compose.project.yml`** — service `webserver`: `build.context ./bin/${PHPVERSION}`, `image: lamp-web:${PHPVERSION}`, `container_name: lamp-${PROJECT_NAME}`, ports `${HTTP_PORT}:80` / `${HTTPS_PORT}:443`, volumes `${PROJECT_DIR}:/var/www/html`, shared php.ini/ssl/vhosts, logs `./logs/${PROJECT_NAME}/apache2` and `./logs/${PROJECT_NAME}/xdebug`, same environment block as old file (keep `TZ`, `extra_hosts`). Joins external network `lamp-net` (`external: true`, `name: lamp-net`). No `depends_on`/`links`.
- [ ] **Step 4: `git rm docker-compose.yml`.**
- [ ] **Step 5: Verify config parses.** Run:
  `docker compose --env-file .env -f compose.shared.yml config -q && docker compose --env-file .env --env-file projects/fazp.env -f compose.project.yml config -q`
  Expected: no output, exit 0.
- [ ] **Step 6: Manual smoke, shared + one project.** Run `dev-services-lease cancel`, then
  `docker compose -p lamp-shared --env-file .env -f compose.shared.yml up -d --build --wait` and
  `docker compose -p lamp-fazp --env-file .env --env-file projects/fazp.env -f compose.project.yml up -d --build`.
  Expected: `curl -sk -o /dev/null -w '%{http_code}' http://localhost:8083/` prints 200 or 3xx; from inside web container `getent hosts database` resolves. Then `docker update --restart=no` on any container started, `dev-services-lease arm`.
- [ ] **Step 7: Commit** `refactor: split compose into shared db stack and per-project web`.

### Task 2: `lamp` script

**Files:**
- Create: `lamp` (executable, bash, `set -euo pipefail`), `tests/lamp_test.sh`
- Modify: none

**Interfaces:**
- Consumes: Task 1 compose files, `projects/<name>.env`, env var names above.
- Produces CLI: `lamp up <p>`, `lamp down <p>`, `lamp restart <p>`, `lamp down-all`, `lamp ls`, `lamp logs <p> [-f]`, `lamp shell <p>`, `lamp help`. Internal functions: `dc()` (compose wrapper), `valid_project <name>`, `running_projects` (prints names of running `lamp-*` web containers excluding `lamp-<DATABASE>` and `lamp-phpmyadmin`), `shared_up`, `shared_down`.

- [ ] **Step 1: Write `tests/lamp_test.sh`** (plain bash asserts, run with `bash tests/lamp_test.sh`). Cases: `lamp help` exit 0; `lamp up nope` exit non-zero and stderr lists `escrybe`, `fazp`, `lps-escrybe`; `lamp up` with project whose `PROJECT_DIR` is missing (temp project file under `projects/`, removed after) exit non-zero and starts no container; `lamp ls` exit 0 with nothing running.
- [ ] **Step 2: Run it, expect FAIL** (`lamp` missing).
- [ ] **Step 3: Implement `lamp`.** Resolve repo dir from the script's real path (`readlink -f`) so a symlink in `~/.local/bin` works; `cd` there. `up`: validate project and dir → `dev-services-lease cancel` → `shared_up` (compose `-p lamp-shared ... up -d --build --wait`) → project `up -d --build` → `docker update --restart=no` on the web container → `dev-services-lease arm` → print `http://localhost:$HTTP_PORT` and `https://localhost:$HTTPS_PORT`. If the project step fails and `running_projects` is empty, run `shared_down` before exiting non-zero. `down`: project `down`; if `running_projects` empty → `shared_down`. `down-all`: every running project, then shared. `ls`: table of running projects with URLs, plus line for MySQL/pma state. Use `/home/peralta/.local/bin/dev-services-lease` by absolute path; if missing, warn and continue.
- [ ] **Step 4: Run `bash tests/lamp_test.sh`, expect all PASS.**
- [ ] **Step 5: Live test (parallel).** `./lamp up fazp && ./lamp up escrybe`; `./lamp ls` shows both; `curl` ports 8083 and 8081 answer; `./lamp up fazp` again is harmless; `./lamp down fazp` leaves MySQL up (`docker ps` shows `lamp-mysql8`); `./lamp down escrybe` stops MySQL and phpMyAdmin. Expected: `docker ps --filter name=lamp-` empty at end. Do not touch Docker daemon.
- [ ] **Step 6: Symlink** `ln -sf "$PWD/lamp" ~/.local/bin/lamp`; `lamp ls` works from another directory.
- [ ] **Step 7: Commit** `feat: add lamp CLI for per-project start/stop`.

### Task 3: Docs

**Files:**
- Modify: `README.md` (add "Multi-project usage" section at top: commands, how to add `projects/x.env`, port table, cookie-across-ports caveat, note `dev_build_container.sh` targets the old single-compose layout and is no longer valid until updated), `sample.env` (remove `DOCUMENT_ROOT`, `HOST_MACHINE_UNSECURE_HOST_PORT`, `HOST_MACHINE_SECURE_HOST_PORT`, `PHPVERSION` lines, comment that they live in `projects/*.env`).
- Modify: `.env` — remove same keys only after Task 2 live test passes (`.env` is local, check `git check-ignore .env`).

- [ ] **Step 1: Edit README and sample.env as above.**
- [ ] **Step 2: Re-run Task 2 Step 5 quickly** to confirm removing the keys from `.env` broke nothing.
- [ ] **Step 3: Commit** `docs: document lamp multi-project usage`.
- [ ] **Step 4: End of task.** Leave services as user wants for testing; run `dev-services-lease arm`; tell user the 1-hour window and expiry.
