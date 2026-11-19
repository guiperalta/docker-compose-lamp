#!/usr/bin/env bash
# Safe tests for ./lamp: none of these start a container.
cd "$(dirname "$(readlink -f "$0")")/.."
fail=0
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

./lamp ls >/dev/null 2>&1 && ok "ls exits 0" || bad "ls exits 0"
exit $fail
