import subprocess
import time
from datetime import datetime

class RadioCommander:
    def get_ts(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def set_state(self, radio_type, state):
        """radio_type: 'bluetooth', 'wifi', or 'all' | state: 'on' or 'off'"""
        action = "block" if state == "off" else "unblock"
        if radio_type == "all":
            print(f"[{self.get_ts()}] [POWER] {state.upper()}ing ALL Radios")
        else:
            print(f"[{self.get_ts()}] [POWER] {state.upper()}ing: {radio_type}")
        subprocess.run(["sudo", "/usr/sbin/rfkill", action, radio_type], capture_output=True)
        time.sleep(0.5)

    def reset_bluetooth(self):
        """Low-level reset for the BLE stack."""
        subprocess.run(["sudo", "pkill", "-9", "gatttool"], stderr=subprocess.DEVNULL)
        subprocess.run("sudo hciconfig hci0 down", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run("sudo hciconfig hci0 up", shell=True, stderr=subprocess.DEVNULL)
        time.sleep(1)
