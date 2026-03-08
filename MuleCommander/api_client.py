import os
import time
import requests
from radio_commander import RadioCommander
from ble_scout import BLEScout
from wifi_navigator import WiFiNavigator

class ProxyClient:
    def __init__(self):
        self.radio = RadioCommander()
        self.scout = BLEScout()
        self.wifi = WiFiNavigator()
        
    def sync_camera_time(self, base_url):
        from rtc_manager import RTCManager
        from datetime import datetime
        import requests
        import re

        rtc = RTCManager()
        if not rtc.enabled: return False
        
        current_rtc_ts = rtc.get_time()
        if not current_rtc_ts: return False
        
        rtc_dt = datetime.fromtimestamp(current_rtc_ts)
        
        try:
            print(f"[PROXY] Forcing Camera Clock Sync to {rtc_dt.strftime('%Y-%m-%d %H:%M:%S')}...")
            d_str = rtc_dt.strftime("%Y-%m-%d")
            t_str = rtc_dt.strftime("%H:%M:%S")
            
            # Unconditionally overwrite the camera's chronological register upon connection
            requests.get(f"{base_url}/?custom=1&cmd=3005&str={d_str}", timeout=4) # Set Date
            time.sleep(0.5)
            requests.get(f"{base_url}/?custom=1&cmd=3006&str={t_str}", timeout=4) # Set Time
            
            print("[PROXY] Time synchronized successfully.")
            return True
            
        except Exception as e:
            print(f"[PROXY] Clock sync request failed: {e}")
            return False

    def _wake_and_connect(self):
        print("[PROXY] Booting Radios & Scanning...")
        self.radio.set_state("all", "off")
        self.radio.reset_bluetooth()
        self.radio.set_state("bluetooth", "on")

        found_devices = self.scout.scan(duration=10)
        mac_list = list(found_devices.keys())

        if not mac_list:
            print("[PROXY] No cameras found via BLE.")
            self.radio.set_state("all", "off")
            return None

        mac = mac_list[0]
        name = found_devices[mac]
        
        creds = self.scout.get_credentials(mac, name)
        if not (creds and creds.is_complete):
            print(f"[PROXY] Failed to get credentials for {name}.")
            self.radio.set_state("all", "off")
            return None

        print("[PROXY] Switching to Wi-Fi...")
        self.radio.set_state("bluetooth", "off")
        self.radio.set_state("wifi", "on")

        if not self.wifi.connect(creds):
            print("[PROXY] Failed to connect to camera Wi-Fi.")
            self.radio.set_state("all", "off")
            return None
            
        # Wake HTTP Stack using manufacturer sequence
        base_url = f"http://{creds.ip_address}"
        try:
            requests.get(f"{base_url}/?custom=1&cmd=3001&par=2", timeout=5)
            time.sleep(1)
            requests.get(f"{base_url}/?custom=1&cmd=3001&par=0", timeout=5)
            time.sleep(1)
        except Exception as e:
            pass
            
        return base_url

    def execute_proxy_action(self, woods_net_action_id, param_val):
        """
        Translates a Woods-Net 0x8X action into a Novatek HTTP Command
        using the proprietary CEYOMUR mapping derived from PCAPdroid.
        """
        
        # --- CEYOMUR PROPRIETARY MAPPING ---
        # 0x80 Set Vid Resol  => cmd=2002 (e.g. 0=4KP30, 3=1080P30, 4=720P30)
        # 0x81 Set Pic Resol  => cmd=1002 (11=30M, 12=25M, 13=21M, 14=16M, 15=12M, 16=8M, 17=4M, 18=2M)
        # 0x82 PIR Sens       => cmd=9003 (0=High, 1=Med, 2=Low)
        # 0x83 Force Photo    => cmd=1001 
        # 0x84 Force Video    => cmd=2001 (1=Start, 0=Stop)
        # 0x85 PIR Delay      => cmd=9002 (seconds elapsed e.g. 60=1min, 135=2m15s)
        # 0x86 Capture Mode   => cmd=9001 (1=Video, 2=Photo+Vid, 0=Photo)
        
        mapping = {
            0x80: ("2002", param_val),
            0x81: ("1002", param_val),
            0x82: ("9003", param_val),
            0x83: ("1001", None),
            0x84: ("2001", param_val),
            0x85: ("9002", param_val),
            0x86: ("9001", param_val),
        }
        
        if woods_net_action_id not in mapping:
            print(f"[PROXY] Unsupported Action ID: {hex(woods_net_action_id)}")
            return False
            
        nv_cmd, nv_par = mapping[woods_net_action_id]
        
        base_url = self._wake_and_connect()
        if not base_url: return False
        
        success = False
        try:
            url = f"{base_url}/?custom=1&cmd={nv_cmd}"
            if nv_par is not None:
                url += f"&par={nv_par}"
                
            print(f"[PROXY] Transmitting HTTP: {url}")
            resp = requests.get(url, timeout=5)
            
            if "<Status>0</Status>" in resp.text:
                 print("[PROXY] Action Success.")
                 success = True
            else:
                 print(f"[PROXY] Action Failed. Response: {resp.text}")
                 
        except Exception as e:
             print(f"[PROXY] Request Error: {e}")
             
        finally:
             print("[PROXY] Tearing down Radios...")
             try: requests.get(f"{base_url}/?custom=1&cmd=9018", timeout=1) # Kill switch
             except: pass
             self.radio.set_state("all", "off")
             
        return success

    def delete_camera_file(self, filename: str, expected_size: int) -> bool:
        """
        Securely deletes a file from the camera's MicroSD card.
        Requires exact byte-size verification via FTP before issuing the delete command
        to prevent accidental deletion of recycled filenames (e.g. IMG0001.JPG).
        """
        from ftplib import FTP
        
        base_url = self._wake_and_connect()
        if not base_url: return False
        
        success = False
        ftp = None
        try:
            # 1. Connect to FTP and Authenticate Size
            ip = base_url.split("//")[1]
            print(f"[PROXY] Authenticating file size via FTP: {ip}")
            ftp = FTP(ip, timeout=10)
            ftp.login(user='root', passwd='')
            ftp.set_pasv(True)
            
            # Camera files are in /DCIM/Photo/ (or /DCIM/Video/ but we only delete JPGs)
            ftp.cwd('/DCIM/Photo/')
            
            try:
                actual_size = ftp.size(filename)
                print(f"[PROXY] File '{filename}' size: {actual_size} bytes (Expected: {expected_size})")
            except Exception as e:
                print(f"[PROXY] Validating size failed (File missing?): {e}")
                actual_size = -1
                
            if actual_size != expected_size:
                print(f"[PROXY] [CRITICAL ERROR] Size mismatch! Refusing to delete '{filename}'!")
                return False
                
            print(f"[PROXY] Size mathematically verified. Executing permanent deletion...")
            
            # 2. Execute HTTP Delete Command (cmd=4003)
            # The URL expects the raw filename string
            url = f"{base_url}/?custom=1&cmd=4003&str={filename}"
            resp = requests.get(url, timeout=5)
            
            if "<Status>0</Status>" in resp.text:
                print(f"[PROXY] Successfully deleted '{filename}'.")
                success = True
            else:
                print(f"[PROXY] HTTP Delete returned failure: {resp.text}")
                
        except Exception as e:
            print(f"[PROXY] Delete flow error: {e}")
            
        finally:
            if ftp:
                try: ftp.quit()
                except: pass
                
            print("[PROXY] Tearing down Radios...")
            try: requests.get(f"{base_url}/?custom=1&cmd=9018", timeout=1) # Kill switch
            except: pass
            self.radio.set_state("all", "off")
            
        return success
