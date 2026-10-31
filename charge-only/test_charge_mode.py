"""Exercise boot gating with fake sysfs, keys and shutdown commands.

Every test uses a private root and stubs for hardware/disk mutations. Nothing
connects to the router or invokes the host's mount/poweroff/insmod commands.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parent / "overlay/opt/mu300/bin/mu300-charge-mode"

STUB = r'''#!PYTHON
import json, os, pathlib, signal, sys, time
name = pathlib.Path(sys.argv[0]).name
root = pathlib.Path(os.environ['MU300_SYSROOT'])
def put(path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
def log(text):
    with open(os.environ['CALL_LOG'], 'a') as handle:
        handle.write(text + '\n')
if name == 'busybox':
    assert sys.argv[1:3] == ['timeout', '-k'], sys.argv
    os.execvp(sys.argv[5], sys.argv[5:])
elif name == 'mu300-device':
    print(os.environ.get('TEST_MODEL', 'u30air'))
elif name == 'mu300-keys':
    log('keys ' + ' '.join(sys.argv[1:]))
    plan = json.loads(os.environ['KEY_PLAN'])
    for step in plan:
        time.sleep(0.06)
        put('proc/uptime', str(step['time']) + '.00 0.00\n')
        if 'supply' in step:
            state = step['supply']
            for path in ('sys/class/power_supply/usb/online',
                         'sys/class/power_supply/bq2560x_charger/online'):
                if state is None:
                    (root/path).unlink(missing_ok=True)
                else:
                    put(path, str(state) + '\n')
            put('sys/class/extcon/extcon0/state', '' if state is None else 'USB=' + str(state) + '\n')
        if step.get('remove_input'):
            (root/'dev/input/event0').unlink(missing_ok=True)
        print(step.get('event', '0 tick'), flush=True)
    if os.environ.get('KEY_HANG'):
        while True:
            time.sleep(1)
elif name == 'sleep':
    text = (root/'proc/uptime').read_text().split()[0]
    put('proc/uptime', str(int(float(text)) + int(sys.argv[1])) + '.00 0.00\n')
    time.sleep(0.03)
elif name == 'poweroff':
    log(name + ' ' + ' '.join(sys.argv[1:]))
    os.kill(os.getppid(), signal.SIGTERM)
elif name == 'mountpoint':
    log(name + ' ' + ' '.join(sys.argv[1:]))
    sys.exit(0)
elif name in ('mount', 'insmod', 'sync', 'mu300-next-boot', 'mu300-led'):
    log(name + ' ' + ' '.join(sys.argv[1:]))
else:
    raise RuntimeError('unexpected stub: ' + name)
'''


class ChargeMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mu300-charge-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for path in ("tmp", "sys/class/net/lo", "sys/class/net/usb0", "root"):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        for path, text in {
            "run/mu300/boot-mode": "charger\n",
            "proc/cmdline": "androidboot.mode=charger modem=shutdown\n",
            "proc/uptime": "0.00 0.00\n",
            "proc/sys/kernel/random/boot_id": "test-boot-id\n",
            "proc/modules": "",
            "sys/class/power_supply/battery/capacity": "53\n",
            "sys/class/power_supply/battery/online": "1\n",
            "sys/class/power_supply/battery/status": "Unknown\n",
            "sys/class/power_supply/battery/temp": "350\n",
            "sys/class/power_supply/bq2560x_charger/online": "1\n",
            "sys/class/power_supply/bq2560x_charger/status": "Charging\n",
            "sys/class/power_supply/usb/online": "1\n",
            "sys/class/extcon/extcon0/state": "USB=1\n",
            "sys/class/input/event0/device/name": "gpio-keys\n",
            "dev/input/event0": "",
        }.items():
            self.put(path, text)
        stub = self.bin / "stub"
        stub.write_text(STUB.replace("#!PYTHON", "#!" + sys.executable, 1))
        stub.chmod(0o755)
        for name in ("busybox", "mu300-device", "mu300-keys", "mu300-led",
                     "mu300-next-boot", "sleep", "poweroff", "mountpoint",
                     "mount", "insmod", "sync"):
            (self.bin / name).symlink_to(stub.name)
        self.log = self.base / "calls.log"
        self.env = dict(os.environ, MU300_SYSROOT=str(self.root),
                        MU300_BIN=str(self.bin), CALL_LOG=str(self.log),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.env.pop("FAILSAFE", None)
        self.env.pop("MU300_POWER_CONF", None)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def read(self, path):
        target = self.root / path
        return target.read_text() if target.exists() else ""

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def run_gate(self, plan=None, action="boot", timeout=12, **environment):
        if plan is None:
            plan = [{"time": 3, "event": "116 long"}]
        env = dict(self.env, KEY_PLAN=json.dumps(plan), **environment)
        proc = subprocess.Popen(["/bin/sh", str(SCRIPT), action], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            self.fail(f"gate hung; stdout={out!r} stderr={err!r} calls={self.calls()!r}")
        self.assertEqual(proc.returncode, 0, err)
        return out

    def assert_released(self, reason):
        self.assertEqual(self.read("run/mu300/power/state"), "active\n")
        self.assertIn(reason, self.read("run/mu300/power/reason"))
        self.assertFalse((self.root / "run/mu300/charging-boot").exists())
        self.assertFalse((self.root / "run/mu300/charge-mode/waiting").exists())
        self.assertFalse((self.root / "run/mu300/charge-mode/keys.fifo").exists())

    def test_normal_boot_is_unchanged(self):
        self.put("run/mu300/boot-mode", "normal\n")
        self.run_gate()
        self.assertEqual(self.calls(), "")
        self.assertFalse((self.root / "run/mu300/power").exists())

    def test_other_board_is_unchanged(self):
        self.run_gate(TEST_MODEL="f50")
        self.assertEqual(self.calls(), "")

    def test_failsafe_is_never_blocked(self):
        self.put("tmp/failsafe", "")
        self.run_gate()
        self.assertEqual(self.calls(), "")

    def test_explicit_auto_start_setting_is_respected(self):
        self.put("etc/mu300/power.conf", "POWER_ON_CHARGER=1\nCHARGE_TO=85\n")
        self.run_gate()
        self.assertEqual(self.calls(), "")
        self.assertEqual(self.read("etc/mu300/power.conf"), "POWER_ON_CHARGER=1\nCHARGE_TO=85\n")

    def test_missing_or_invalid_policy_defaults_to_wait(self):
        self.put("etc/mu300/power.conf", "POWER_ON_CHARGER=garbage\n")
        self.run_gate()
        self.assert_released("power button held")

    def test_only_held_power_releases_and_leds_keep_updating(self):
        self.run_gate([
            {"time": 1, "event": "138 short"},
            {"time": 4, "event": "138 long"},
            {"time": 5, "event": "116 short"},
            {"time": 10},
            {"time": 13, "event": "116 long"},
        ])
        self.assert_released("power button held for three seconds")
        self.assertGreaterEqual(self.calls().count("mu300-led battery"), 3)
        events = self.read("run/mu300/charge-mode/events.log")
        self.assertIn("ignored key event: 138 short", events)
        self.assertIn("ignored key event: 138 long", events)
        self.assertIn("ignored key event: 116 short", events)
        self.assertNotIn("poweroff", self.calls())
        self.assertEqual(self.read("run/mu300/boot-mode"), "charger\n")

    def test_cable_bounce_does_not_power_off(self):
        self.run_gate([
            {"time": 1, "supply": 0},
            {"time": 2, "supply": 1},
            {"time": 4, "supply": 0},
            {"time": 5, "supply": 1},
            {"time": 8, "event": "116 long"},
        ])
        self.assert_released("power button held")
        self.assertNotIn("poweroff", self.calls())

    def test_unplug_ignores_battery_online_and_stale_charging_status(self):
        self.run_gate([
            {"time": 1, "supply": 0},
            {"time": 2},
            {"time": 3},
        ])
        calls = self.calls().splitlines()
        rearm = calls.index("mu300-next-boot --rearm")
        root_ro = calls.index("mount -o remount,ro /")
        disk_ro = calls.index("mount -o remount,ro /mnt/mu300-disk")
        off = calls.index("poweroff -f")
        self.assertLess(rearm, root_ro)
        self.assertLess(root_ro, disk_ro)
        self.assertLess(disk_ro, off)
        self.assertIn("sync ", calls[disk_ro:off])
        self.assertEqual(self.read("run/mu300/power/state"), "charging-boot\n")
        self.assertIn("powering off", self.read("root/mu300-charge-mode/events.log"))

    def test_missing_input_is_recoverable(self):
        (self.root / "dev/input/event0").unlink()
        self.run_gate()
        self.assert_released("input or supply unavailable")
        self.assertNotIn("keys ", self.calls())

    def test_missing_initial_supplies_are_recoverable(self):
        for name in ("usb", "bq2560x_charger"):
            (self.root / f"sys/class/power_supply/{name}/online").unlink()
        self.put("sys/class/extcon/extcon0/state", "")
        self.run_gate()
        self.assert_released("input or supply unavailable")

    def test_supply_readings_disappearing_is_recoverable(self):
        self.run_gate([{"time": n, "supply": None} for n in range(1, 8)])
        self.assert_released("supply readings disappeared")

    def test_key_reader_exit_is_recoverable(self):
        self.run_gate([{"time": 1}])
        self.assert_released("key reader stopped responding")

    def test_input_disappearing_is_recoverable(self):
        self.run_gate([{"time": 1, "remove_input": True}])
        self.assert_released("power-key input disappeared")

    def test_wait_has_no_automatic_start_timeout(self):
        self.run_gate([
            {"time": 360}, {"time": 1800},
            {"time": 1803, "event": "116 long"},
        ])
        events = self.read("root/mu300-charge-mode/events.log")
        self.assertIn("six-minute charging wait reached", events)
        self.assertIn("1803 continuing normal boot: power button held", events)
        self.assert_released("power button held")

    def test_repeated_command_cannot_suspend_active_device(self):
        self.put("run/mu300/power/state", "active\n")
        self.run_gate()
        self.assertEqual(self.calls(), "")

    def test_read_only_check_reports_live_prerequisites(self):
        out = self.run_gate(action="check")
        self.assertIn("charger boot: charging-only policy", out)
        self.assertIn("supply=0", out)
        self.assertIn("power-key input=ready", out)
        self.assertEqual(self.calls(), "")

    def test_device_tree_mode_fallback(self):
        (self.root / "run/mu300/boot-mode").unlink()
        self.put("proc/cmdline", "console=ttyS1\n")
        self.put("proc/device-tree/chosen/bootargs", "sprdboot.mode=charger\0")
        self.run_gate()
        self.assert_released("power button held")


if __name__ == "__main__":
    unittest.main(verbosity=2)
