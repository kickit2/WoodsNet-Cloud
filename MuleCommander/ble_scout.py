import pexpect
import re
import time
from datetime import datetime
from dataclasses import dataclass

@dataclass
class CameraCredentials:
    ssid_prefix: str = None
    full_ssid: str = None
    password: str = None
    ip_address: str = None
    mac: str = None
    name: str = None

    @property
    def is_complete(self):
        return bool(self.ssid_prefix and self.password and self.ip_address)

class BLEScout:
    def __init__(self, target_prefix="HTC"):
        self.target_prefix = target_prefix
        self.handle_notify = "0x001f"
        self.handle_cmd = "0x0019"

    def get_ts(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def scan(self, duration=10):
        found_devices = {}
        print(f"[{self.get_ts()}] [SCANNER] Scanning for '{self.target_prefix}' ({duration}s)...")
        try:
            child = pexpect.spawn("bluetoothctl", encoding='utf-8')
            child.sendline("scan on")
            start_time = time.time()
            while time.time() - start_time < duration:
                try:
                    index = child.expect([r"Device ([0-9A-F:]{17}) (.*)", pexpect.TIMEOUT], timeout=1)
                    if index == 0:
                        mac = child.match.group(1)
                        name = child.match.group(2).strip().split(" ")[-1]
                        if self.target_prefix in name and mac not in found_devices:
                            found_devices[mac] = name
                            print(f"[{self.get_ts()}]   >>> FOUND: {name} [{mac}]")
                except: continue
            child.sendline("scan off")
            child.close()
        except Exception as e:
            print(f"[{self.get_ts()}] [!] Scan Error: {e}")
        return found_devices

    def get_credentials(self, mac, name):
        creds = CameraCredentials(mac=mac, name=name)
        print(f"[{self.get_ts()}] [*] [{name}] BLE: Handshake started...")
        try:
            gatt = pexpect.spawn(f"gatttool -I -b {mac}", encoding='utf-8', timeout=30)
            gatt.sendline("connect")
            if gatt.expect(["Connection successful", "Error"], timeout=15) != 0:
                print(f"[{self.get_ts()}] [!] [{name}] BLE: Connection timeout")
                return None
            
            print(f"[{self.get_ts()}] [*] [{name}] BLE: Connected. Requesting Notifications...")
            gatt.sendline(f"char-write-req {self.handle_notify} 0100")
            gatt.expect("successfully", timeout=5)
            
            start_time = time.time()
            last_poke = 0
            while time.time() - start_time < 30:
                if creds.is_complete:
                    print(f"[{self.get_ts()}] [*] [{name}] BLE: All credentials received.")
                    gatt.sendline("disconnect")
                    gatt.close()
                    return creds
                
                if time.time() - last_poke > 3:
                    print(f"[{self.get_ts()}] [*] [{name}] BLE: Requesting SSID/PW/IP...")
                    gatt.sendline(f"char-write-cmd {self.handle_cmd} 4745545344") # GETSD
                    time.sleep(0.5)
                    gatt.sendline(f"char-write-cmd {self.handle_cmd} 4745545044") # GETPD
                    last_poke = time.time()

                try:
                    index = gatt.expect([r"Notification handle = 0x001e value: ([0-9a-fA-F ]+)", "disconnect"], timeout=1)
                    if index == 0:
                        self._parse_packet(creds, gatt.match.group(1), name)
                except: continue
        except Exception as e:
            print(f"[{self.get_ts()}] [!] [{name}] BLE Exception: {e}")
        return None

    def _parse_packet(self, creds, hex_str, name):
        clean_hex = hex_str.replace(" ", "")
        try:
            ascii_str = bytes.fromhex(clean_hex).decode('utf-8', errors='ignore')
            clean_str = ascii_str.replace('\x00', '').strip()
            if "[SD]" in clean_str:
                creds.ssid_prefix = re.sub(r'[^a-zA-Z0-9-]', '', clean_str.split("[SD]")[1])
                print(f"[{self.get_ts()}] [*] [{name}]    >>> Received SSID: {creds.ssid_prefix}")
            if "[PD]" in clean_str:
                creds.password = re.sub(r'[^a-zA-Z0-9]', '', clean_str.split("[PD]")[1])
                print(f"[{self.get_ts()}] [*] [{name}]    >>> Received PASS: {creds.password}")
            if "5b42545d" in clean_hex:
                ip_bytes = bytes.fromhex(clean_hex[-8:])
                if len(ip_bytes) == 4:
                    creds.ip_address = ".".join(map(str, ip_bytes))
                    print(f"[{self.get_ts()}] [*] [{name}]    >>> Received IP: {creds.ip_address}")
        except: pass
