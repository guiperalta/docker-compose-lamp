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

./lamp ls >/dev/null 2>&1 && ok "ls exits 0" || bad "ls exits 0"
exit $fail
