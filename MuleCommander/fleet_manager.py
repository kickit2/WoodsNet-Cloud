import time
from radio_commander import RadioCommander
from ble_scout import BLEScout
from wifi_navigator import WiFiNavigator
from data_harvester import DataHarvester
from image_crusher import ImageCrusher # The only new import
import rtc_manager
import api_client
import uploader

import random

class FleetManager:
    def __init__(self):
        self.radio = RadioCommander()
        self.scout = BLEScout()
        self.wifi = WiFiNavigator()
        self.harvester = DataHarvester()
        self.crusher = ImageCrusher()
        
        # Read Hardware Routing DIP Switches
        self.is_relay_mode, self.target_relay_id = self.read_dip_switches()

    def read_dip_switches(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            # Define BCM pins for SW0, SW1, SW2, SW3
            sw_pins = [5, 6, 13, 19] 
            GPIO.setup(sw_pins, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            
            # Inverted logic: ON = switch pulled to GND = logic LOW (0) -> True in software
            sw0 = not GPIO.input(5)
            sw1 = not GPIO.input(6)
            sw2 = not GPIO.input(13)
            sw3 = not GPIO.input(19)
            
            # SW0 [Logic LOW / ON]: Relay mode
            if sw0:
                # SW1-SW3 define Relay ID (e.g., Low-Low-Low -> 1 1 1 -> 7)
                relay_id = (sw1 << 2) | (sw2 << 1) | sw3
                return True, relay_id
            else:
                return False, 0
                
        except Exception as e:
            print(f"GPIO Error reading DIP switches, defaulting to Base mode: {e}")
            return False, 0
            
    def _handle_collision_backoff(self):
        print("\n--- INITIATING COLLISION BACKOFF ---")
        try:
            import os
            retry_count = 0
            retry_file = '/media/cam_grabs/retry_count.txt'
            if os.path.exists(retry_file):
                with open(retry_file, 'r') as f:
                    try: retry_count = int(f.read().strip())
                    except: pass
                    
            retry_count += 1
            print(f"Collision Backoff Retry Count: {retry_count}")
            
            with open(retry_file, 'w') as f:
                f.write(str(retry_count))
                
            sleep_duration = 7200 # Default 2 hours if max retries
            if retry_count < 3:
                # Random 30-90 minute sleep offset
                sleep_duration = random.randint(30*60, 90*60)
                print(f"Applying dynamic offset: sleeping for {sleep_duration} seconds.")
                
            from rtc_manager import RTCManager
            rtc = RTCManager()
            rtc.set_wakeup_alarm(sleep_duration)
            
            # The exact power-down logic should mirror Prime Shutdown, but handled by execute_prime_shutdown later
            return sleep_duration
            
        except Exception as e:
            print(f"Error during Collision Backoff: {e}")
            return random.randint(30*60, 90*60)

    def run_mission(self, target_mp=3.0, quality=55, speed=11):
        print("\n--- MULE COMMANDER V6.2 (STREAMING ARCHITECTURE): MISSION START ---")
        
        has_more_files = True
        batch_number = 1
        
        while has_more_files:
            print(f"\n=========================================")
            print(f"       STARTING STREAM BATCH {batch_number}")
            print(f"=========================================")
            
            # --- 1. BOOT RADIOS & CONNECT ---
            self.radio.set_state("all", "off")
            self.radio.reset_bluetooth()
            self.radio.set_state("bluetooth", "on")
            
            found_devices = self.scout.scan(duration=10)
            mac_list = list(found_devices.keys())
            
            # If no cameras found, we abort entirely
            if not mac_list:
                print("No cameras found in BLE scan. Aborting mission.")
                break
                
            for i, mac in enumerate(mac_list):
                name = found_devices[mac]
                is_last = (i == len(mac_list) - 1)
                
                creds = self.scout.get_credentials(mac, name)
                if creds and creds.is_complete:
                    self.radio.set_state("bluetooth", "off")
                    self.radio.set_state("wifi", "on")
                    
                    if self.wifi.connect(creds):
                        try:
                            from api_client import ProxyClient
                            proxy = ProxyClient()
                            proxy.sync_camera_time(f"http://{creds.ip_address}")
                        except Exception as e:
                            print(f"Failed to sync camera time: {e}")
                            
                        # Harvest up to 70MB! The new sync() returns True if the camera has remaining files.
                        has_more_files = self.harvester.sync(creds.ip_address, mac, name, max_bytes=70*1024*1024)
                        
            # --- 2. TEAR DOWN WIFI & CRUSH BATCH ---
            print("\n--- TEARING DOWN WIFI: STARTING 70MB PROXIMITY CRUSH ---")
            self.radio.set_state("all", "off")
            
            self.crusher.crush(
                target_mp=target_mp, 
                quality=quality, 
                speed=speed, 
                delete_source=True
            )
            
            # --- 3. SHATTER GHOST LOCKS ---
            import subprocess
            import os
            import glob
            try:
                my_pid = os.getpid()
                subprocess.run(f"kill -9 $(pgrep python3 | grep -v {my_pid})", shell=True, stderr=subprocess.DEVNULL)
                time.sleep(1)
            except Exception as e:
                pass

            # --- 4. UPLOAD AVIF BATCH TO BASE STATION ---
            if self.is_relay_mode:
                print(f"\n--- BATCH {batch_number} CRUSH COMPLETE: STARTING SPI UPLOAD (RELAY ID {self.target_relay_id}) ---")
            else:
                print(f"\n--- BATCH {batch_number} CRUSH COMPLETE: STARTING SPI UPLOAD (BASE STATION) ---")
                
            try:
                from uploader import MuleUploader
                uploader = MuleUploader(is_relay_mode=self.is_relay_mode, target_relay_id=self.target_relay_id)
                uploader.start()
                
                # Check Base Station Tasks
                has_session = uploader.negotiate_state_machine()
                if not has_session:
                    print("Could not negotiate session (Network Busy / No Response). Applying collision backoff.")
                    uploader.stop()
                    backoff_duration = self._handle_collision_backoff()
                    
                    # Instead of normal prime, we force sleep with backoff duration
                    try:
                        uploader = MuleUploader()
                        uploader.execute_prime_shutdown(sleep_duration=backoff_duration)
                    except Exception as e:
                        print(f"Forced Backoff Shutdown Error: {e}")
                        import sys
                        logging.info("Core execution loop concluded. Intentional exit to drop XBee SPI locks."); sys.exit(0)
                
                target_dir = "/media/cam_grabs/"
                files = glob.glob(os.path.join(target_dir, "*.AVIF")) + glob.glob(os.path.join(target_dir, "*.avif"))
                
                if not files:
                     print("No AVIF files to upload in this batch.")
                else: 
                    for f in files:
                        print(f"Uploading {f} (Blast Mode)...")
                        if uploader.send_file_blast(f):
                            print(f"Uploaded: {f}")
                            try:
                                if os.path.exists(f): os.remove(f)
                                print(f"Deleted source: {f}")
                                
                                jpg_match = os.path.splitext(f)[0] + ".JPG"
                                if os.path.exists(jpg_match): os.remove(jpg_match)
                                    
                            except OSError: pass
                        else:
                            print(f"Failed to upload: {f}. It will remain for the next batch.")
                        
                uploader.stop()
                
            except ImportError:
                print("ERROR: Could not import MuleUploader")
            except Exception as e:
                print(f"ERROR during Upload Phase: {e}")
                
            batch_number += 1
            
        # The loop has naturally terminated (has_more_files = False).
        print("\n--- MULE STREAMING MISSION COMPLETE ---")
        
        # WE NOW EXPLICITLY COMMAND THE OS SHUTDOWN HERE, ALLOWING THE MULE TO SLEEP UNTIL THE NEXT DAY.
        try:
            # Phase 13: Time-Division Multiplexed Power Management
            sleep_duration = 7200 # Default 2 hours if Base Station never assigned a schedule
            
            try:
                import os
                if os.path.exists('/media/cam_grabs/next_wake.txt'):
                    with open('/media/cam_grabs/next_wake.txt', 'r') as f:
                        next_wake_ts = int(f.read().strip())
                    
                    from rtc_manager import RTCManager
                    rtc = RTCManager()
                    current_ts = rtc.get_time()
                    
                    if next_wake_ts > current_ts:
                        sleep_duration = next_wake_ts - current_ts
                        print(f"\n[TDM PRE-FLIGHT] RTC Time: {current_ts} | Target Wake: {next_wake_ts}")
                        print(f"[TDM PRE-FLIGHT] Dispatching Dynamic Sleep Duration: {sleep_duration} seconds.")
                    else:
                        print(f"\n[TDM PRE-FLIGHT] Target Wake time has already passed! Defaulting to 2-hour sleep.")
            except Exception as e:
                print(f"TDM Calculation Error: {e}")
                
            from uploader import MuleUploader
            uploader = MuleUploader()
            # Note: execute_prime_shutdown explicitly halts the Linux OS.
            # This is the absolute final script action; no code will execute natively after this block.
            uploader.execute_prime_shutdown(sleep_duration=sleep_duration)
            logging.info("Core execution loop concluded. Intentional exit to drop XBee SPI locks."); sys.exit(0)
        except Exception as e: 
            print(f"Critical Shutdown Exception: {e}")

if __name__ == "__main__":
    manager = FleetManager()
    manager.run_mission()
