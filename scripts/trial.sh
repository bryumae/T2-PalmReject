#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
usage() {
    echo 'Usage: sudo scripts/trial.sh --probe|--passthrough|--filter [--recovery-ready] [--device PATH] [--config FILE] [--session-uid UID] [--duration SECONDS]'
    echo 'Live duration: 1–86400 seconds; default 60. Manual launch only.'
    echo '--probe checks service access without reading events, creating devices or grabbing input.'
    echo 'Build unprivileged first. Connect and verify a USB mouse and keyboard.'
}
mode= device= config= recovery=0 session_uid= helper_pid=
duration=60 duration_arg=
while (( $# )); do
    case "$1" in
        --duration)
            (( $# >= 2 )) && [[ -z "$duration_arg" ]] || { usage; exit 2; }
            duration_arg="$2"
            [[ "$duration_arg" =~ ^[1-9][0-9]{0,4}$ ]] && (( duration_arg <= 86400 )) || { usage; exit 2; }
            duration="$duration_arg"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --probe|--passthrough|--filter) [[ -z "$mode" ]] || { usage; exit 2; }; mode="$1"; shift ;;
        --device|--config|--session-uid)
            (( $# >= 2 )) || { usage; exit 2; }
            if [[ "$1" == --device ]]; then device="$2";
            elif [[ "$1" == --config ]]; then config="$2"; else session_uid="$2"; fi
            shift 2 ;;
        --recovery-ready) recovery=1; shift ;;
        *) usage; exit 2 ;;
    esac
done
[[ -n "$mode" ]] || { usage; exit 2; }
[[ "$mode" != --probe || -z "$duration_arg" ]] || { usage; exit 2; }
[[ "$mode" == --probe || "$recovery" == 1 ]] || { usage; exit 2; }
[[ "$mode" != --probe || -z "$config" ]] || { usage; exit 2; }
[[ "$mode" != --filter || -n "$config" ]] || { usage; exit 2; }
[[ "$mode" != --passthrough || -z "$config" ]] || { usage; exit 2; }
[[ "$mode" == --filter || -z "$session_uid" ]] || { usage; exit 2; }
(( EUID == 0 )) || { echo 'Run this launcher through sudo after reviewing/building the source.' >&2; exit 1; }
[[ -x "$root_dir/palmreject" ]] || { echo 'Run make as the ordinary user first.' >&2; exit 1; }
if [[ "$mode" == --filter ]]; then
    session_uid="${session_uid:-${SUDO_UID:-}}"
    [[ "$session_uid" =~ ^[1-9][0-9]*$ ]] || { echo 'Filtering requires a nonroot --session-uid or SUDO_UID.' >&2; exit 2; }
    account="$(getent passwd "$session_uid")"
    IFS=: read -r session_name _ actual_uid session_group _ <<< "$account"
    [[ "$actual_uid" == "$session_uid" ]] || exit 2
    active_sessions=0
    for session in $(loginctl show-user "$session_uid" -p Sessions --value); do
        [[ "$(loginctl show-session "$session" -p Active --value)" == yes ]] || continue
        [[ "$(loginctl show-session "$session" -p Type --value)" == wayland ]] || continue
        # Desktop can be empty even in a valid KDE session. The helper verifies
        # the actual KWin owner, device identity and cancellation API before grab.
        [[ "$(loginctl show-session "$session" -p User --value)" == "$session_uid" ]] || continue
        active_sessions=$((active_sessions+1))
    done
    [[ "$active_sessions" == 1 && -S "/run/user/$session_uid/bus" ]] || {
        echo 'Filtering requires exactly one active Wayland session and a user bus for that UID.' >&2; exit 1;
    }
    runuser -u "$session_name" -- /usr/bin/python3 -c 'import dbus' || exit 1
fi
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
    if [[ -n "$helper_pid" ]]; then
        kill "$helper_pid" >/dev/null 2>&1 || true
        wait "$helper_pid" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$trial_dir"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
install -m755 "$root_dir/palmreject" "$trial_dir/palmreject"
# A binary created under /run can otherwise remain in systemd's init_t domain.
# Label only this disposable copy; use the normal executable transition rather
# than granting init_t input access or changing SELinux enforcement/policy.
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
    chcon -t bin_t -- "$trial_dir/palmreject"
fi
mkdir -m700 "$trial_dir/state"
if [[ "$mode" == --filter ]]; then
    chgrp "$session_group" "$trial_dir" "$trial_dir/state"
    chmod 0750 "$trial_dir"
    chmod 2750 "$trial_dir/state"
    install -m755 "$root_dir/scripts/gesture-helper.py" "$trial_dir/gesture-helper.py"
fi
args=()
[[ -z "$device" ]] || args+=(--device "$device")
# Probe is read-only. The process validates the descriptor again after launching.
probe="$("$trial_dir/palmreject" --probe "${args[@]}")"
IFS=' ' read -r field _ <<< "$probe"
device="${field#device=}"
[[ "$device" =~ ^/dev/input/event[0-9]+$ ]] || { echo 'Probe returned an invalid node.' >&2; exit 1; }
args=("$mode" --device "$device" --state-dir "$trial_dir/state")
[[ "$mode" == --probe ]] || args+=(--duration "$duration")
[[ "$mode" != --filter ]] || args+=(--session-uid "$session_uid")
if [[ -n "$config" ]]; then
    install -m600 -- "$config" "$trial_dir/profile.conf"
    args+=(--config "$trial_dir/profile.conf")
fi
# No boot enablement, sleep hook, module load, input group, or broad device access.
# The classifier is not allowed to read even its virtual node until it reports it.
started=1
run_options=()
[[ "$mode" != --probe ]] || run_options+=(--wait --pipe)
systemd-run "${run_options[@]}" --unit="$unit" --service-type=exec \
    -p Conflicts=sleep.target -p 'Before=sleep.target kait2en-suspend.service t2-services-suspend.service' \
    -p Restart=no -p "RuntimeMaxSec=$duration" -p TimeoutStopSec=2 -p KillMode=control-group \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes \
    -p PrivateNetwork=yes -p RestrictAddressFamilies='AF_UNIX AF_NETLINK' \
    -p CapabilityBoundingSet= -p ProtectKernelTunables=yes -p ProtectKernelModules=yes \
    -p ProtectControlGroups=yes -p RestrictSUIDSGID=yes -p LockPersonality=yes \
    -p DevicePolicy=closed -p "DeviceAllow=/dev/uinput rw" -p "DeviceAllow=$device r" \
    -p "ReadWritePaths=$trial_dir/state" \
    "$trial_dir/palmreject" "${args[@]}"
[[ "$mode" != --probe ]] || exit 0
invocation="$(systemctl show -p InvocationID --value "$unit")"
journal_args=(-u "$unit")
[[ ! "$invocation" =~ ^[a-f0-9]{32}$ ]] || journal_args=("_SYSTEMD_INVOCATION_ID=$invocation")
# Permit precisely the newly created virtual node, so libinput can classify it.
# This is a runtime cgroup update; it grants no access to keyboards or other mice.
virtual=
for (( attempt=0; attempt<120; attempt++ )); do
    if [[ -s "$trial_dir/state/virtual-device" ]]; then
        virtual="$(cat "$trial_dir/state/virtual-device")"
        [[ "$virtual" =~ ^/dev/input/event[0-9]+$ ]] || exit 1
        event="${virtual##*/}"
        sys_path="$(readlink -f -- "/sys/class/input/$event/device")"
        [[ "$sys_path" == /sys/devices/virtual/input/* ]] || exit 1
        [[ "$(cat "$sys_path/name")" == 'PalmReject MacBookPro16,1 Touchpad' ]] || exit 1
        systemctl set-property --runtime "$unit" \
            "DeviceAllow=/dev/uinput rw" "DeviceAllow=$device r" "DeviceAllow=$virtual rw"
        if [[ "$mode" == --filter ]]; then
            runuser -u "$session_name" -- env \
                "XDG_RUNTIME_DIR=/run/user/$session_uid" \
                "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$session_uid/bus" \
                /usr/bin/python3 "$trial_dir/gesture-helper.py" --socket "$trial_dir/state/control.sock" &
            helper_pid=$!
        fi
        break
    fi
    systemctl is-active --quiet "$unit" || break
    sleep 0.1
done
[[ -n "$virtual" ]] || { journalctl "${journal_args[@]}" -n 40 --no-pager; exit 1; }
echo "Emergency stop: sudo systemctl stop $unit"
echo "Trial will stop automatically after $duration seconds. Ctrl+C also stops it."
while systemctl is-active --quiet "$unit"; do sleep 0.2; done
journalctl "${journal_args[@]}" -n 40 --no-pager
result="$(systemctl show -p Result --value "$unit")"
[[ "$result" == success || "$result" == timeout ]]
