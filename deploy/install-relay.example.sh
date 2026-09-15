#!/bin/sh
# Run ONLY on the operator's own new Ubuntu/Debian relay server with sudo.
# This service forwards encrypted TLS bytes. Certificates remain on the Mac.
set -eu
test "$(id -u)" = 0 || { printf '%s\n' 'Run with sudo on your own relay server.'; exit 1; }
unit=/etc/systemd/system/codex-console-relay.service
test ! -e "$unit" || { printf '%s\n' 'Relay unit exists; refusing to overwrite.'; exit 1; }
if ss -ltn '( sport = :443 )' | tail -n +2 | read -r line; then
    printf '%s\n' 'Port 443 is already in use. Configure your existing proxy instead.'
    exit 1
fi
apt-get update
apt-get install -y socat
cat > "$unit" <<'UNIT'
[Unit]
Description=Codex console encrypted TCP relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
DynamicUser=yes
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ExecStart=/usr/bin/socat TCP-LISTEN:443,reuseaddr,fork TCP:127.0.0.1:19443
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now codex-console-relay.service
printf '%s\n' 'Relay ready. Allow TCP 443 in your cloud/host firewall; keep 19443 private.'
