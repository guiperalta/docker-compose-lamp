#!/usr/bin/env bash
# Safe tests for ./lamp: none of these start a container.
cd "$(dirname "$(readlink -f "$0")")/.."
fail=0
# tests must never touch the real ~/.local/bin, ~/.config/systemd or the running timer
export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.docker}"
export HOME=$(mktemp -d); export LAMP_SKIP_SYSTEMCTL=1
trap 'rm -rf "$HOME"' EXIT
ok()  { echo "PASS: $1"; }
bad() { echo "FAIL: $1"; fail=1; }

./lamp help >/dev/null 2>&1 && ok "help exits 0" || bad "help exits 0"

err=$(./lamp up nope 2>&1 >/dev/null); rc=$?
[ $rc -ne 0 ] && ok "unknown project exits non-zero" || bad "unknown project exits non-zero"
for p in escrybe fazp lps-escrybe; do
  echo "$err" | grep -q "$p" && ok "unknown project lists $p" || bad "unknown project lists $p"
done

printf 'PROJECT_NAME=zz-missing\nPROJECT_DIR=./does-not-exist\nPHPVERSION=php83\nHTTP_PORT=8999\nHTTPS_PORT=8998\n' > projects/zz-missing.env
./lamp up zz-missing >/dev/null 2>&1; rc=$?
rm -f projects/zz-missing.env
[ $rc -ne 0 ] && ok "missing dir exits non-zero" || bad "missing dir exits non-zero"
[ -z "$(docker ps -aq --filter name=lamp-zz-missing)" ] && ok "missing dir starts no container" || bad "missing dir starts no container"

# WRITABLE_DIRS are created (idempotent, nested ok) by `lamp prep`, no container needed
tmp=$(mktemp -d)
printf 'PROJECT_NAME=zz-prep\nPROJECT_DIR=%s\nPHPVERSION=php83\nHTTP_PORT=8997\nHTTPS_PORT=8996\nWRITABLE_DIRS="temp_not_auto_delete a/b"\n' "$tmp" > projects/zz-prep.env
./lamp prep zz-prep >/dev/null 2>&1; rc=$?
[ $rc -eq 0 ] && ok "prep exits 0" || bad "prep exits 0"
[ -d "$tmp/temp_not_auto_delete" ] && [ -w "$tmp/temp_not_auto_delete" ] && ok "prep creates writable dir" || bad "prep creates writable dir"
[ -d "$tmp/a/b" ] && ok "prep creates nested dir" || bad "prep creates nested dir"
./lamp prep zz-prep >/dev/null 2>&1 && ok "prep idempotent" || bad "prep idempotent"
rm -f projects/zz-prep.env; rm -rf "$tmp"

# per-project Dockerfile layer: `lamp config` shows resolved compose config
mkdir -p "$tmp2" 2>/dev/null; tmp2=$(mktemp -d)
printf 'PROJECT_NAME=zz-pkg\nPROJECT_DIR=%s\nPHPVERSION=php83\nHTTP_PORT=8995\nHTTPS_PORT=8994\n' "$tmp2" > projects/zz-pkg.env
cfg=$(./lamp config zz-pkg 2>&1)
echo "$cfg" | grep -q 'image: lamp-web:php83' && ok "no project Dockerfile -> base image" || bad "no project Dockerfile -> base image"
printf 'ARG PHPVERSION\nFROM lamp-web:php83\nRUN true\n' > projects/zz-pkg.Dockerfile
cfg=$(./lamp config zz-pkg 2>&1)
echo "$cfg" | grep -q 'dockerfile: zz-pkg.Dockerfile' && ok "project Dockerfile used" || bad "project Dockerfile used"
echo "$cfg" | grep -q 'image: lamp-zz-pkg:latest' && ok "project image tag" || bad "project image tag"
rm -f projects/zz-pkg.env projects/zz-pkg.Dockerfile; rm -rf "$tmp2"

# `lamp init` on a fresh checkout (copy of tracked files only): .env, ssl cert, data/log dirs
fresh=$(mktemp -d)
git ls-files -z | xargs -0 -I{} cp --parents {} "$fresh" 2>/dev/null
( cd "$fresh" && ./lamp init >/dev/null 2>&1 ); rc=$?
[ $rc -eq 0 ] && ok "init exits 0" || bad "init exits 0"
[ -f "$fresh/.env" ] && ok "init creates .env" || bad "init creates .env"
[ -f "$fresh/config/ssl/dev-selfsigned.crt" ] && [ -f "$fresh/config/ssl/dev-selfsigned.key" ] && ok "init creates ssl cert+key" || bad "init creates ssl cert+key"
[ -d "$fresh/data/mysql" ] && [ -d "$fresh/logs/mysql" ] && ok "init creates data/log dirs" || bad "init creates data/log dirs"
[ -f "$fresh/config/php/php.ini" ] && [ -d "$fresh/config/vhosts" ] && ok "tracked config present on fresh checkout" || bad "tracked config present on fresh checkout"
sum1=$(sha256sum "$fresh/config/ssl/dev-selfsigned.crt")
( cd "$fresh" && ./lamp init >/dev/null 2>&1 ) && [ "$sum1" = "$(sha256sum "$fresh/config/ssl/dev-selfsigned.crt")" ] && ok "init idempotent (cert kept)" || bad "init idempotent (cert kept)"
# guard: php.ini missing or a directory must stop `lamp up` before docker can create a dir there
for state in missing dir; do
  fresh2=$(mktemp -d); git ls-files -z | xargs -0 -I{} cp --parents {} "$fresh2" 2>/dev/null
  rm -f "$fresh2/config/php/php.ini"; [ $state = dir ] && mkdir "$fresh2/config/php/php.ini"
  err=$(cd "$fresh2" && ./lamp up escrybe 2>&1 >/dev/null); rc=$?
  [ $rc -ne 0 ] && echo "$err" | grep -q 'php.ini' && ok "up refuses when php.ini is $state" || bad "up refuses when php.ini is $state"
  [ ! -d "$fresh2/config/php/php.ini" ] || [ $state = dir ] || bad "php.ini dir not created ($state)"
  rm -rf "$fresh2"
done
rm -rf "$fresh"

# LAMP_HOST in .env is honoured in URLs, never printed literally
out=$(./lamp ls 2>&1)
echo "$out" | grep -q '\${' && bad "ls prints no unexpanded variables" || ok "ls prints no unexpanded variables"
if [ -n "$(docker ps -q --filter label=com.docker.compose.service=webserver --filter name=lamp-)" ]; then
  echo "$out" | grep -q 'http://localhost:' && ok "ls uses default host localhost" || bad "ls uses default host localhost"
fi

# timer: off/on/status in a copy, with a fake lease so the real timer is untouched
tcopy=$(mktemp -d); git ls-files -z | xargs -0 -I{} cp --parents {} "$tcopy" 2>/dev/null
fakel=$(mktemp); printf '#!/bin/sh\necho "$1" >> "%s.log"\n' "$fakel" > "$fakel"; chmod +x "$fakel"
( cd "$tcopy" && export LAMP_LEASE="$fakel"
  ./lamp timer off >/dev/null 2>&1; [ "$(./lamp timer status)" = disabled ] && echo ok1
  ./lamp timer on >/dev/null 2>&1;  [ ! -e .lamp-no-timer ] && echo ok2 ) > "$tcopy/res" 2>&1
grep -q ok1 "$tcopy/res" && ok "timer off -> status disabled" || bad "timer off -> status disabled"
grep -q ok2 "$tcopy/res" && ok "timer on removes the flag" || bad "timer on removes the flag"
grep -q cancel "$fakel.log" && ok "timer off cancels the lease" || bad "timer off cancels the lease"
# install into a fake HOME: symlinks to repo files, backup of a different old file, idempotent, uninstall
fh=$(mktemp -d); mkdir -p "$fh/.local/bin"; echo old > "$fh/.local/bin/dev-services-lease"
( cd "$tcopy" && env -u LAMP_LEASE HOME="$fh" LAMP_SKIP_SYSTEMCTL=1 ./lamp timer install ) >/dev/null 2>&1
[ "$(readlink -f "$fh/.local/bin/dev-services-lease")" = "$(readlink -f "$tcopy/timer/dev-services-lease")" ] && ok "timer install links lease to repo" || bad "timer install links lease to repo"
[ -f "$fh/.local/bin/dev-services-lease.bak" ] && ok "timer install keeps a different old file as .bak" || bad "timer install keeps a different old file as .bak"
[ -L "$fh/.config/systemd/user/dev-services-cleanup.timer" ] && ok "timer install links the systemd units" || bad "timer install links the systemd units"
( cd "$tcopy" && env -u LAMP_LEASE HOME="$fh" LAMP_SKIP_SYSTEMCTL=1 ./lamp timer install ) >/dev/null 2>&1 && ok "timer install is idempotent" || bad "timer install is idempotent"
st=$( cd "$tcopy" && env -u LAMP_LEASE HOME="$fh" ./lamp timer status ); [ "$st" != missing ] && ok "status not missing after install" || bad "status not missing after install"
( cd "$tcopy" && env -u LAMP_LEASE HOME="$fh" LAMP_SKIP_SYSTEMCTL=1 ./lamp timer uninstall ) >/dev/null 2>&1
st=$( cd "$tcopy" && env -u LAMP_LEASE HOME="$fh" ./lamp timer status ); [ "$st" = missing ] && ok "status missing after uninstall" || bad "status missing after uninstall"
rm -rf "$tcopy" "$fh" "$fakel" "$fakel.log"

./lamp ls >/dev/null 2>&1 && ok "ls exits 0" || bad "ls exits 0"
exit $fail
