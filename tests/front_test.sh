#!/usr/bin/env bash
# Live test (starts containers): every project's HTTP port must answer BOTH plain HTTP and TLS,
# because Chrome upgrades http://localhost:PORT to https://localhost:PORT.
# Usage: bash tests/front_test.sh [phpNN ...]   (default: php83)
cd "$(dirname "$(readlink -f "$0")")/.."
fail=0
ok()  { echo "PASS: $1"; }
bad() { echo "FAIL: $1"; fail=1; }
tmp=$(mktemp -d); chmod 755 "$tmp"
echo '<?php echo "ok ", PHP_VERSION, " host=", $_SERVER["SERVER_NAME"], " https=", ($_SERVER["HTTPS"] ?? "off");' > "$tmp/index.php"
chmod 644 "$tmp/index.php"
n=0
for php in "${@:-php83}"; do
  n=$((n+1)); name="zz-front-$php"; hp=$((8900+n*2)); sp=$((8900+n*2+1))
  printf 'PROJECT_NAME=%s\nPROJECT_DIR=%s\nPHPVERSION=%s\nHTTP_PORT=%s\nHTTPS_PORT=%s\n' "$name" "$tmp" "$php" "$hp" "$sp" > "projects/$name.env"
  ./lamp up "$name" >/dev/null 2>&1 || bad "$php: lamp up"
  sleep 2
  p=$(curl -s -m 8 "http://localhost:$hp/");               [[ $p == ok* ]] && ok "$php plain HTTP on :$hp" || bad "$php plain HTTP on :$hp (got: ${p:0:60})"
  t=$(curl -sk -m 8 "https://localhost:$hp/");             [[ $t == ok*https=on* ]] && ok "$php TLS on the same port :$hp" || bad "$php TLS on the same port :$hp (got: ${t:0:60})"
  d=$(curl -sk -m 8 "https://localhost:$sp/");             [[ $d == ok* ]] && ok "$php direct HTTPS port :$sp" || bad "$php direct HTTPS port :$sp"
  case "$p" in *host=localhost*) ok "$php SERVER_NAME is localhost";; *) bad "$php SERVER_NAME is localhost";; esac
  ./lamp down "$name" >/dev/null 2>&1; rm -f "projects/$name.env"
done
rm -rf "$tmp"
exit $fail
