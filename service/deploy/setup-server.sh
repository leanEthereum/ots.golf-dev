#!/usr/bin/env bash
# One-shot setup of the verifier + site on a fresh Ubuntu 24.04 host (run as root once).
#
#   OTS_DOMAIN=ots.golf bash deploy/setup-server.sh
#
# What it does: creates the unprivileged user `ots`, installs elan, Go (for landrun), uv and Caddy,
# clones the contract repository, builds the verification tools and the warm Lean build, installs
# the two systemd units (web, worker) and the Caddy site. Secrets go in /etc/ots/secrets.env.
set -euo pipefail

: "${OTS_REPO_URL:=https://github.com/leanEthereum/ots.golf-dev}"
: "${OTS_SUBMISSIONS_REPO:=leanEthereum/ots.golf-submissions}"
: "${OTS_DOMAIN:=localhost}"
OTS_HOME=/srv/ots
[[ "${EUID}" == 0 ]] || { echo 'run this installer as root' >&2; exit 1; }
[[ "${OTS_REPO_URL}" =~ ^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/?$ ]] || {
  echo 'OTS_REPO_URL must be a GitHub HTTPS repository URL' >&2; exit 1;
}
[[ "${OTS_SUBMISSIONS_REPO}" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$ ]] || {
  echo 'OTS_SUBMISSIONS_REPO must be owner/repository' >&2; exit 1;
}
core_repo="${OTS_REPO_URL#https://github.com/}"
core_repo="${core_repo%/}"
core_repo="${core_repo%.git}"
[[ "${core_repo,,}" != "${OTS_SUBMISSIONS_REPO,,}" ]] || {
  echo 'the core and submissions repositories must be different' >&2; exit 1;
}
[[ "${OTS_DOMAIN}" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || {
  echo 'OTS_DOMAIN must be a hostname' >&2; exit 1;
}
mem_gb=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
(( mem_gb >= 30 )) || { echo 'at least 32 GB of installed RAM is required' >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'this installer currently supports x86_64 Linux only' >&2; exit 1; }

apt-get update
apt-get install -y git curl build-essential python3 gnupg sudo openssl sqlite3 debian-keyring debian-archive-keyring apt-transport-https
# Go, current release from go.dev (landrun needs 1.24+; Ubuntu's golang-go is older)
if ! /usr/local/go/bin/go version >/dev/null 2>&1; then
  go_ver="$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1)"
  curl -fsSL "https://go.dev/dl/${go_ver}.linux-amd64.tar.gz" -o /tmp/go.tgz
  rm -rf /usr/local/go && tar -C /usr/local -xzf /tmp/go.tgz && rm /tmp/go.tgz
fi
# Caddy (TLS + reverse proxy)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --batch --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy

id -u ots >/dev/null 2>&1 || useradd --system --create-home --home-dir "${OTS_HOME}" --shell /bin/bash ots
getent group ots-state >/dev/null || groupadd --system ots-state
usermod -aG ots-state ots
id -u ots-web >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/ots-web --gid ots-state --shell /usr/sbin/nologin ots-web
install -d -o ots -g ots-state -m 2770 "${OTS_HOME}/data" "${OTS_HOME}/data/logs" /srv/ots-work
chmod o+x "${OTS_HOME}"
# Bounded job storage: a fully allocated (not sparse) 48 GiB image on the system disk, mounted at
# /srv/ots-work at every boot. A runaway proof can fill only this volume.
work_image=/var/lib/ots-work.img
if ! mountpoint -q /srv/ots-work; then
  if [[ ! -f "${work_image}" ]]; then
    fallocate -l 48G "${work_image}"
    chmod 600 "${work_image}"
    mkfs.ext4 -q -m 0 -E nodiscard "${work_image}"   # discard would punch holes into the image
  fi
  grep -q "^${work_image} " /etc/fstab || echo "${work_image} /srv/ots-work ext4 loop,nosuid,nodev 0 2" >> /etc/fstab
  mount /srv/ots-work
fi
chown ots:ots-state /srv/ots-work
chmod 2770 /srv/ots-work
loginctl enable-linger ots   # systemd --user for the sandbox scope of the worker
# Only ots-web receives secrets. The verifier's different Unix identity must never receive them,
# including through /proc/<pid>/environ. The shared group grants database/log access, not credentials.
mkdir -p /etc/ots
[[ -f /etc/ots/public.env ]] || cat > /etc/ots/public.env <<ENV
OTS_BASE_URL=https://${OTS_DOMAIN}
OTS_CONTRACT_REPO=${core_repo}
OTS_SUBMISSIONS_REPO=${OTS_SUBMISSIONS_REPO}
OTS_DATABASE_URL=sqlite:///${OTS_HOME}/data/ots.db
OTS_DATA_DIR=${OTS_HOME}/data
OTS_WORK_DIR=/srv/ots-work
TMPDIR=/srv/ots-work
OTS_PHONY=1
ENV
[[ -f /etc/ots/secrets.env ]] || ( umask 077; cat > /etc/ots/secrets.env <<ENV
GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 32)
GITHUB_TOKEN=
ENV
)
chown root:root /etc/ots/public.env /etc/ots/secrets.env
chmod 644 /etc/ots/public.env && chmod 600 /etc/ots/secrets.env

sudo -u ots -H bash -euo pipefail <<USER
cd "${OTS_HOME}"
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="\$HOME/.elan/bin:\$HOME/.local/bin:/usr/local/go/bin:\$PATH"
[[ -d repo/.git ]] || git clone "${OTS_REPO_URL}" repo
cd repo
verifier/setup_tools.sh
( cd formal && lake exe cache get && lake build )   # the contract only: submissions are compiled in the sandbox, never here
python3 verifier/pin_contract.py check
( cd service && uv sync --locked )
USER

install -m 644 "${OTS_HOME}/repo/service/deploy/ots-web.service" /etc/systemd/system/
install -m 644 "${OTS_HOME}/repo/service/deploy/ots-worker.service" /etc/systemd/system/
# the worker's memory backstop: 6 GB below the machine, at most the unit's 28G (the sandboxed run
# itself is capped at the contract's 24 GiB by verify.py)
cap=$(( mem_gb - 6 )); (( cap > 28 )) && cap=28
sed -i "s/^MemoryMax=.*/MemoryMax=${cap}G/" /etc/systemd/system/ots-worker.service
sed "s/{{DOMAIN}}/${OTS_DOMAIN}/" "${OTS_HOME}/repo/service/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable ots-web ots-worker caddy
echo "installed, not started. Configure /etc/ots/secrets.env and complete deploy/README.md's Linux acceptance checks before public admission."
