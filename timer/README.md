# Auto-stop timer

One-hour "testing window" for local dev containers. After the last start, the timer fires once
and stops the tracked containers (never the Docker daemon) and `dev-session-*` user services.

| File | Role |
|---|---|
| `dev-services-lease` | `arm` / `cancel` / `cleanup-now` / `status` for the timer |
| `dev-services-cleanup` | what runs when the hour ends |
| `dev-services-cleanup.timer` / `.service` | systemd user units (one-shot, no `[Install]`) |

`lamp timer install` (also run by `lamp init`) symlinks these into `~/.local/bin` and
`~/.config/systemd/user`, so the repo stays the single source of truth and other tools that call
`~/.local/bin/dev-services-lease` keep working. Existing different files are kept as `*.bak`.
`lamp timer uninstall` removes the symlinks.
