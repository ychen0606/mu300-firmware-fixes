#!/bin/sh
# Run the gate in the router's real BusyBox ash with fake sysfs and safe stubs.
# Usage: sh smoke_on_device.sh /tmp/.../mu300-charge-mode
set -eu
gate=$1
testdir=$(mktemp -d /tmp/mu300-charge-smoke.XXXXXX)
trap 'rm -rf "$testdir"' EXIT
mkdir -p "$testdir/bin"
cat > "$testdir/bin/mu300-device" <<'EOF'
#!/bin/sh
echo u30air
EOF
cat > "$testdir/bin/mu300-led" <<'EOF'
#!/bin/sh
echo "led $*" >> "$MU300_SYSROOT/calls"
EOF
cat > "$testdir/bin/mu300-keys" <<'EOF'
#!/bin/sh
if [ "$SMOKE_CASE" = power ]; then
    echo '138 short'; sleep 1
    echo '116 short'; sleep 1
    echo '138 long'; sleep 1
    echo '116 long'; sleep 5
else
    for n in 1 2 3 4 5; do echo '0 tick'; sleep 1; done
fi
EOF
cat > "$testdir/bin/mutation-stub" <<'EOF'
#!/bin/sh
name=${0##*/}
echo "$name $*" >> "$MU300_SYSROOT/calls"
[ "$name" != poweroff ] || kill -TERM "$PPID"
exit 0
EOF
chmod 755 "$testdir"/bin/*
ln -s /opt/mu300/bin/busybox "$testdir/bin/busybox"
for cmd in mount mountpoint insmod sync poweroff mu300-next-boot; do
    ln -s mutation-stub "$testdir/bin/$cmd"
done
export MU300_BIN=$testdir/bin
export PATH=$testdir/bin:$PATH
for SMOKE_CASE in power unplug; do
    export SMOKE_CASE
    export MU300_SYSROOT=$testdir/$SMOKE_CASE
    mkdir -p "$MU300_SYSROOT"/run/mu300 "$MU300_SYSROOT"/proc/sys/kernel/random \
        "$MU300_SYSROOT"/sys/class/power_supply/usb \
        "$MU300_SYSROOT"/sys/class/power_supply/battery \
        "$MU300_SYSROOT"/sys/class/input/event0/device \
        "$MU300_SYSROOT"/sys/class/net/lo "$MU300_SYSROOT"/dev/input
    ln -s /proc/uptime "$MU300_SYSROOT/proc/uptime"
    cp /proc/sys/kernel/random/boot_id "$MU300_SYSROOT/proc/sys/kernel/random/boot_id"
    : > "$MU300_SYSROOT/proc/modules"
    echo charger > "$MU300_SYSROOT/run/mu300/boot-mode"
    echo gpio-keys > "$MU300_SYSROOT/sys/class/input/event0/device/name"
    : > "$MU300_SYSROOT/dev/input/event0"
    echo 53 > "$MU300_SYSROOT/sys/class/power_supply/battery/capacity"
    echo 350 > "$MU300_SYSROOT/sys/class/power_supply/battery/temp"
    echo Charging > "$MU300_SYSROOT/sys/class/power_supply/battery/status"
    echo 1 > "$MU300_SYSROOT/sys/class/power_supply/battery/online"
    connected=1
    [ "$SMOKE_CASE" != unplug ] || connected=0
    echo "$connected" > "$MU300_SYSROOT/sys/class/power_supply/usb/online"
    /opt/mu300/bin/busybox timeout -k 2 20 /bin/sh "$gate" boot
    if [ "$SMOKE_CASE" = power ]; then
        [ "$(cat "$MU300_SYSROOT/run/mu300/power/state")" = active ]
        grep -q 'power button held' "$MU300_SYSROOT/run/mu300/power/reason"
        [ ! -e "$MU300_SYSROOT/run/mu300/charging-boot" ]
        ! grep -q '^poweroff' "$MU300_SYSROOT/calls"
    else
        [ "$(cat "$MU300_SYSROOT/run/mu300/power/state")" = charging-boot ]
        grep -qx 'poweroff -f' "$MU300_SYSROOT/calls"
        grep -qx 'mount -o remount,ro /' "$MU300_SYSROOT/calls"
    fi
    echo "PASS: device ash $SMOKE_CASE (fake hardware)"
done
