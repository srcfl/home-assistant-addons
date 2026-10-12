#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:?usage: test_restore_data_owner.sh IMAGE}
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
tool="${root}/scripts/restore_data_owner.sh"

run_case() {
  docker run --rm -i --network none --user 0:0 --workdir / --entrypoint bash \
    --mount "type=bind,src=${tool},dst=/recovery.sh,readonly" \
    "${image}" -se
}

run_case <<'CASE'
rm -rf /data
mkdir -p '/data/driver cache/release'
printf 'private fixture bytes\n' >/data/config.yaml
chmod 0600 /data/config.yaml
printf 'driver fixture bytes\n' >'/data/driver cache/release/driver.lua'
chmod 0640 '/data/driver cache/release/driver.lua'
ln -s 'driver cache/release' /data/selected
ln -s selected /data/previous
before=$(sha256sum /data/config.yaml '/data/driver cache/release/driver.lua')
bash /recovery.sh
test "$(stat -c '%u:%g:%a' /data/config.yaml)" = 100:101:600
test "$(stat -c '%u:%g:%a' '/data/driver cache/release/driver.lua')" = 100:101:640
test "$(stat -c '%u:%g' /data/previous)" = 100:101
test "$(readlink /data/previous)" = selected
test "$(readlink /data/selected)" = 'driver cache/release'
test "$(sha256sum /data/config.yaml '/data/driver cache/release/driver.lua')" = "$before"
bash /recovery.sh
test "$(sha256sum /data/config.yaml '/data/driver cache/release/driver.lua')" = "$before"
printf 'pass: private modes, bytes, internal links, repeat\n'
CASE

for kind in external broken cyclic hard root-link; do
  # The case name is fixed here, never input from the data being recovered.
  run_case <<CASE
rm -rf /data /outside
mkdir /data /outside
printf 'old data\n' >/data/config.yaml
printf 'outside bytes\n' >/outside/private
chmod 0600 /data/config.yaml /outside/private
case '${kind}' in
 external) ln -s /outside/private /data/link ;;
 broken) ln -s missing /data/link ;;
 cyclic) ln -s other /data/link; ln -s link /data/other ;;
 hard) ln /outside/private /data/link ;;
 root-link) mv /data/config.yaml /outside/config.yaml; rmdir /data; ln -s /outside /data ;;
esac
before=\$(sha256sum /data/config.yaml /outside/private)
if bash /recovery.sh; then
  printf 'unsafe case accepted: ${kind}\n' >&2
  exit 1
fi
test "\$(stat -c '%u:%g:%a' /data/config.yaml)" = 0:0:600
test "\$(stat -c '%u:%g:%a' /outside/private)" = 0:0:600
test "\$(sha256sum /data/config.yaml /outside/private)" = "\$before"
printf 'pass: rejects ${kind} before changes\n'
CASE
done

# A real nested bind mount must stop recovery before changing /data itself.
nested=$(mktemp -d)
trap 'rm -rf -- "$nested"' EXIT
docker run --rm --network none --user 0:0 --workdir / --entrypoint bash \
  --mount "type=bind,src=${tool},dst=/recovery.sh,readonly" \
  --mount "type=bind,src=${nested},dst=/data/external" \
  "${image}" -ceu '
    before=$(stat -c %u:%g /data)
    if bash /recovery.sh; then exit 1; fi
    test "$(stat -c %u:%g /data)" = "$before"
    printf "pass: rejects nested mount before changes\n"
  '

printf 'Data owner recovery checks passed.\n'
