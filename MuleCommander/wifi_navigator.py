import subprocess
import time
from datetime import datetime

class WiFiNavigator:
    def __init__(self, interface="wlan0"):
        self.interface = interface

    def get_ts(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def connect(self, creds):
        print(f"[{self.get_ts()}] [*] [{creds.name}] WIFI: Searching for full SSID '{creds.ssid_prefix}*'...")
        # Resolve full SSID
        for i in range(15):
            cmd = ["sudo", "nmcli", "-f", "SSID", "dev", "wifi", "list", "--rescan", "yes"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            for line in res.stdout.split('\n'):
                ssid = line.strip()
                if creds.ssid_prefix and creds.ssid_prefix in ssid:
                    creds.full_ssid = ssid
                    print(f"[{self.get_ts()}] [*] [{creds.name}] WIFI: Found Full SSID: {creds.full_ssid}")
                    break
            if creds.full_ssid: break
            time.sleep(1)

        if not creds.full_ssid:
            print(f"[{self.get_ts()}] [!] [{creds.name}] WIFI: Full SSID not found in time.")
            return False

        print(f"[{self.get_ts()}] [*] [{creds.name}] WIFI: Initiating connection...")
        cmd = ["sudo", "nmcli", "dev", "wifi", "connect", creds.full_ssid, "password", creds.password, "ifname", self.interface]
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            print(f"[{self.get_ts()}] [*] [{creds.name}] WIFI: Connected. Waiting for DHCP...")
            time.sleep(5)
            return True
        else:
            print(f"[{self.get_ts()}] [!] [{creds.name}] WIFI: Connection failed.")
        return False
