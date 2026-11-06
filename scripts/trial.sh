#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
usage() {
    echo 'Usage: sudo scripts/trial.sh --passthrough|--filter --recovery-ready [--device PATH] [--config FILE]'
    echo 'Build unprivileged first. Connect and verify a USB mouse and keyboard.'
}
mode= device= config= recovery=0
while (( $# )); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --passthrough|--filter) [[ -z "$mode" ]] || { usage; exit 2; }; mode="$1"; shift ;;
        --device|--config)
            (( $# >= 2 )) || { usage; exit 2; }
            if [[ "$1" == --device ]]; then device="$2"; else config="$2"; fi
            shift 2 ;;
        --recovery-ready) recovery=1; shift ;;
        *) usage; exit 2 ;;
    esac
done
[[ -n "$mode" && "$recovery" == 1 ]] || { usage; exit 2; }
[[ "$mode" != --filter || -n "$config" ]] || { usage; exit 2; }
[[ "$mode" != --passthrough || -z "$config" ]] || { usage; exit 2; }
(( EUID == 0 )) || { echo 'Run this launcher through sudo after reviewing/building the source.' >&2; exit 1; }
[[ -x "$root_dir/palmreject" ]] || { echo 'Run make as the ordinary user first.' >&2; exit 1; }
unit=palmreject-trial.service
# Refuse to overwrite any prior unit or drop-ins; this makes revert safe below.
state="$(systemctl show -p LoadState --value "$unit")"
[[ "$state" == not-found ]] || { echo "Existing $unit detected; inspect it before proceeding." >&2; exit 1; }
for base in /etc/systemd/system /run/systemd/system /run/systemd/system.control; do
    [[ ! -e "$base/$unit" && ! -e "$base/$unit.d" ]] || { echo 'Existing trial configuration found.' >&2; exit 1; }
done
trial_dir="$(mktemp -d /run/palmreject-trial.XXXXXXXX)"
started=0
cleanup() {
    if (( started )); then
        systemctl stop "$unit" >/dev/null 2>&1 || true
        systemctl revert "$unit" >/dev/null 2>&1 || true
        systemctl reset-failed "$unit" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$trial_dir"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
install -m755 "$root_dir/palmreject" "$trial_dir/palmreject"
mkdir -m700 "$trial_dir/state"
args=()
[[ -z "$device" ]] || args+=(--device "$device")
# Probe is read-only. The process validates the descriptor again after launching.
probe="$("$trial_dir/palmreject" --probe "${args[@]}")"
IFS=' ' read -r field _ <<< "$probe"
device="${field#device=}"
[[ "$device" =~ ^/dev/input/event[0-9]+$ ]] || { echo 'Probe returned an invalid node.' >&2; exit 1; }
args=("$mode" --device "$device" --state-dir "$trial_dir/state")
if [[ -n "$config" ]]; then
    install -m600 -- "$config" "$trial_dir/profile.conf"
    args+=(--config "$trial_dir/profile.conf")
fi
# No boot enablement, sleep hook, module load, input group, or broad device access.
# The classifier is not allowed to read even its virtual node until it reports it.
started=1
systemd-run --unit="$unit" --service-type=exec \
    -p Conflicts=sleep.target -p 'Before=sleep.target kait2en-suspend.service t2-services-suspend.service' \
    -p Restart=no -p RuntimeMaxSec=60 -p TimeoutStopSec=2 -p KillMode=control-group \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes \
    -p PrivateNetwork=yes -p RestrictAddressFamilies='AF_UNIX AF_NETLINK' \
    -p CapabilityBoundingSet= -p ProtectKernelTunables=yes -p ProtectKernelModules=yes \
    -p ProtectControlGroups=yes -p RestrictSUIDSGID=yes -p LockPersonality=yes \
    -p DevicePolicy=closed -p "DeviceAllow=/dev/uinput rw" -p "DeviceAllow=$device r" \
    -p "ReadWritePaths=$trial_dir/state" \
    "$trial_dir/palmreject" "${args[@]}"
# Permit precisely the newly created virtual node, so libinput can classify it.
# This is a runtime cgroup update; it grants no access to keyboards or other mice.
virtual=
for (( attempt=0; attempt<70; attempt++ )); do
    if [[ -s "$trial_dir/state/virtual-device" ]]; then
        virtual="$(cat "$trial_dir/state/virtual-device")"
        [[ "$virtual" =~ ^/dev/input/event[0-9]+$ ]] || exit 1
        event="${virtual##*/}"
        sys_path="$(readlink -f -- "/sys/class/input/$event/device")"
        [[ "$sys_path" == /sys/devices/virtual/input/* ]] || exit 1
        [[ "$(cat "$sys_path/name")" == 'PalmReject MacBookPro16,1 Touchpad' ]] || exit 1
        systemctl set-property --runtime "$unit" \
            "DeviceAllow=/dev/uinput rw" "DeviceAllow=$device r" "DeviceAllow=$virtual rw"
        break
    fi
    systemctl is-active --quiet "$unit" || break
    sleep 0.1
done
[[ -n "$virtual" ]] || { journalctl -u "$unit" -n 30 --no-pager; exit 1; }
echo "Emergency stop: sudo systemctl stop $unit"
echo 'Trial will stop automatically after 60 seconds. Ctrl+C also stops it.'
while systemctl is-active --quiet "$unit"; do sleep 0.2; done
journalctl -u "$unit" -n 40 --no-pager
result="$(systemctl show -p Result --value "$unit")"
[[ "$result" == success || "$result" == timeout ]]
