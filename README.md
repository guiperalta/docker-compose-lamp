# LAMP stack for local development (multi-project)

Docker LAMP stack, built to run **several projects in parallel** from one repo. One command per project. Same image, only the folder changes. For local development only, not production.

- **Apache + PHP** (one container per project)
- **MySQL 8 + phpMyAdmin** (one shared instance, started and stopped automatically)
- PHP versions: **8.1, 8.2, 8.3, 8.4, 8.5, 8.6** (`php81` ... `php86`)

> **Security:** the images use the floating `php:<version>-apache-bookworm` tags, so a rebuild picks up the newest patch release. Run `lamp rebuild <project>` regularly. PHP 8.1 is end-of-life upstream (no more fixes): use 8.2+ for anything that matters.

## New machine: setup

1. Install Docker with the compose plugin. Add your user to the `docker` group. Needs `openssl` and `flock` (util-linux).
2. `git clone https://github.com/guiperalta/docker-compose-lamp && cd docker-compose-lamp`
3. `ln -sf "$PWD/lamp" ~/.local/bin/lamp` (puts `lamp` on your PATH)
4. `lamp init` creates `.env` from `sample.env`, the self-signed SSL cert, the `data/` and `logs/` dirs, and tells you which project folders are missing.
5. Put each project folder next to this repo with the name in `projects/<name>.env` (`www-escrybe`, `www-fazp`, `www-lps-escrybe`). They are separate from this repo.
6. Database: empty on a new machine. To keep old data, `mysqldump` on the old machine and import through phpMyAdmin, or copy `data/mysql`.
7. `lamp up escrybe`

Ports that must be free: 3306, 8080, 8443 and each project's ports below. If your uid is not 1000, build with `--build-arg PUID=$(id -u) --build-arg PGID=$(id -g)` (see `bin/php83/Dockerfile`).

## Daily use

```bash
lamp up fazp        # start project (starts shared MySQL + phpMyAdmin if needed)
lamp down fazp      # stop project (MySQL stops when the last project stops)
lamp restart fazp
lamp rebuild fazp   # pull newest PHP patch release (security fixes), rebuild, start
lamp ls             # running projects + URLs
lamp logs fazp -f
lamp shell fazp
lamp down-all
lamp config fazp    # resolved compose config (debug)
lamp init           # first run on a new machine
```

| Project | Folder | HTTP | HTTPS |
|---|---|---|---|
| escrybe | `www-escrybe` | 8081 | 8481 |
| lps-escrybe | `www-lps-escrybe` | 8082 | 8482 |
| fazp | `www-fazp` | 8083 | 8483 |

Shared: MySQL `127.0.0.1:3306` (one instance, one database per project), phpMyAdmin `http://localhost:8080` (user `root`, password from `.env`).

URLs use `localhost` (fazp rejects any other host). Chrome upgrades `http://localhost:PORT` to `https://localhost:PORT`, so every project's HTTP port also answers TLS: a small `haproxy` container per project (`lamp-<name>-front`, config in `config/haproxy/haproxy.cfg`) looks at the first bytes and forwards plain HTTP to Apache's port 80 and TLS to its port 443. Both `http://` and `https://` work on the same port. The browser warns once about the self-signed certificate. Change the host with `LAMP_HOST=` in `.env`; `127.0.0.1` is never upgraded by Chrome but fazp rejects it.

Caveat: browsers share cookies across `localhost` ports, so logins of two projects can overwrite each other. HTTPS uses a self-signed cert: the browser warns once.

## Top-bar app (GNOME)

A small indicator in the Ubuntu top bar shows every project (● running, ⏸ paused, ○ stopped, with CPU and RAM) and the running count. Install with `topbar/install.sh` (autostart at login, starts now; `topbar/install.sh --remove` undoes it). It needs `python3-gi`, `gir1.2-ayatanaappindicator3-0.1` and the GNOME AppIndicator extension; the script checks and prints the `apt` line if something is missing.

- **Click the icon, then "Open panel…"**: a small always-on-top window with Open in browser, Start, Pause/Resume, Restart and Stop for each project, plus Open phpMyAdmin and Stop all. It **stays open** after Start, Stop, Pause, Restart and Stop all (GNOME closes tray menus on every click, so the panel exists for that). Only the "Open in browser" and "Open phpMyAdmin" buttons close it. Esc or the window X also closes it.
- The tray menu has the same actions as quick shortcuts. Pause freezes the web container only; MySQL keeps running.
- **Auto-stop timer** (the 1h dev-services lease that stops containers after a test window): the panel shows the time left, with **Disable** / **Enable** and **+1h** buttons; the tray has the same under "Auto-stop timer". From a terminal: `lamp timer` (status), `lamp timer off`, `lamp timer on` (re-arms 1h). Disabled is remembered in `.lamp-no-timer` (not committed), so `lamp up` stops re-arming it until you enable it again. The timer lives in this repo (`timer/`, see `timer/README.md`): `lamp init` (or `lamp timer install`) symlinks it into `~/.local/bin` and `~/.config/systemd/user`, so a new machine gets it too. It stops only containers (and `dev-session-*` user services), never the Docker daemon. Until it is installed the panel says so and its buttons are off.
- Terminal view of the same table: `python3 topbar/lamp_indicator.py --status`.
- Tests: `python3 tests/topbar_test.py`, `xvfb-run -a python3 tests/topbar_panel_test.py`, `dbus-run-session -- xvfb-run -a python3 tests/topbar_wiring_test.py`.

## Per-project setup

Each project has `projects/<name>.env`:

| Variable | Meaning |
|---|---|
| `PROJECT_NAME` | name, container is `lamp-<name>` |
| `PROJECT_DIR` | project folder (mounted at `/var/www/html`) |
| `PHPVERSION` | `php81` ... `php86` |
| `HTTP_PORT`, `HTTPS_PORT` | host ports |
| `WRITABLE_DIRS` | optional, e.g. `"temp_not_auto_delete"`. Created and made writable by `lamp up` |

**Extra packages:** drop `projects/<name>.Dockerfile` next to the env file. It layers on the base image, e.g.

```dockerfile
FROM lamp-web:php83
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg imagemagick && rm -rf /var/lib/apt/lists/*
```

`lamp up <name>` builds it (cached) as `lamp-<name>:latest`. No file = base image. escrybe has one (ghostscript, weasyprint). Use the same `FROM lamp-web:<your PHPVERSION>` as the project.

**Add a project:** create `projects/<name>.env`. No YAML edits.

## Layout

- `lamp`: the CLI. `compose.shared.yml` (MySQL + phpMyAdmin), `compose.project.yml` (web container).
- `config/`: `vhosts/` (Apache), `php/php.ini` (shared PHP settings), `initdb/` (SQL run on first MySQL start), `ssl/` (generated by `lamp init`, not in git).
- `bin/php81..php86`, `bin/mysql8`, ...: Dockerfiles. `tests/lamp_test.sh`: `bash tests/lamp_test.sh`.
- `dev_build_container.sh` targets the old single-compose layout and does not work until updated.
- Apache vhost `config/vhosts` is shared by all projects (it has a rewrite for tracking URLs that points to escrybe's `/pages/errors/tracking-url.php`).

## Settings

`.env` holds shared values (DB credentials, phpMyAdmin ports, paths). `sample.env` documents them. Default MySQL root password is `tiger`: change it if the machine is shared.

PHP extensions installed: mysqli, pdo_mysql, pdo_sqlite, mbstring, zip, intl, curl, xml, gd, imagick, xdebug (see the Dockerfiles). To add one for a single project, use the per-project Dockerfile. To add one for all, edit `bin/phpXX/Dockerfile` and run `lamp rebuild <project>`.

## Xdebug

Xdebug comes installed by default and it's version depends on the PHP version chosen in the `".env"` file.

**Xdebug versions:**

PHP <= 7.3: Xdebug 2.X.X

PHP >= 7.4: Xdebug 3.X.X

To use Xdebug you need to enable the settings in the ``config/php/php.ini` (shared) ` file according to the chosen version PHP.

Example:

```
# Xdebug 2
#xdebug.remote_enable=1
#xdebug.remote_autostart=1
#xdebug.remote_connect_back=1
#xdebug.remote_host = host.docker.internal
#xdebug.remote_port=9000

# Xdebug 3
#xdebug.mode=debug
#xdebug.start_with_request=yes
#xdebug.client_host=host.docker.internal
#xdebug.client_port=9003
#xdebug.idekey=VSCODE
```

Xdebug VS Code: you have to install the Xdebug extension "PHP Debug". After installed, go to Debug and create the launch file so that your IDE can listen and work properly.

Example:

**VERY IMPORTANT:** the `pathMappings` depends on how you have opened the folder in VS Code. Each folder has your own configurations launch, that you can view in `.vscode/launch.json`

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Listen for Xdebug",
      "type": "php",
      "request": "launch",
      // "port": 9000, // Xdebug 2
      "port": 9003, // Xdebug 3
      "pathMappings": {
        // "/var/www/html": "${workspaceFolder}/www" // if you have opened VSCODE in root folder
        "/var/www/html": "${workspaceFolder}" // if you have opened VSCODE in ./www folder
      }
    }
  ]
}
```

Now, make a breakpoint and run debug.

**Tip!** After theses configurations, you may need to restart container.

## Why you shouldn't use this stack unmodified in production

In production at a minimum: php-fpm instead of mod_php, restricted MySQL users, no phpMyAdmin, real certificates, and no dev tools (xdebug).
