import os
import time
import requests
from ftplib import FTP
from datetime import datetime

class DataHarvester:
    def __init__(self, storage_path="/media/cam_grabs"):
        self.storage_path = storage_path
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

    def get_ts(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _get_ftp(self, ip):
        ftp = FTP(ip, timeout=10)
        ftp.login(user='root', passwd='')
        ftp.set_pasv(True)
        return ftp

    def sync(self, ip, mac, name, max_bytes=70*1024*1024):
        base_url = f"http://{ip}"
        unique_id = mac.replace(':', '')[-6:]
        download_count = 0
        skip_count = 0
        current_batch_bytes = 0
        has_more_files = False
        ftp = None

        try:
            print(f"[{self.get_ts()}] [*] [{name}] HTTP: Sending Wake-Up...")
            requests.get(f"{base_url}/?custom=1&cmd=3001&par=2", timeout=5)

            print(f"[{self.get_ts()}] [*] [{name}] FTP: Logging in...")
            ftp = self._get_ftp(ip)
            ftp.cwd('/DCIM/')
            all_items = ftp.nlst()
            folders = [f for f in all_items if '.' not in f]

            for folder in folders:
                if has_more_files: break # Break outer loop if batch is full
                
                ftp.cwd(f'/DCIM/{folder}/')
                files = ftp.nlst()
                print(f"[{self.get_ts()}] [*] [{name}] FTP: Checking {len(files)} items in {folder}...")

                for filename in files:
                    if not filename.upper().endswith('.JPG'): continue

                    try: remote_size = ftp.size(filename)
                    except: remote_size = -1

                    # Inject the exact byte size into the filename so the Base Station 
                    # can mathematically verify the camera hasn't overwritten the image 
                    # before issuing a blind delete command over the HTTP API.
                    if remote_size > 0:
                        parts = filename.rsplit('.', 1)
                        local_filename = f"{unique_id}_{parts[0]}_SZ{remote_size}.{parts[1]}"
                    else:
                        local_filename = f"{unique_id}_{filename}"

                    local_path = os.path.join(self.storage_path, local_filename)

                    if os.path.exists(local_path):
                        if os.path.getsize(local_path) == remote_size:
                            skip_count += 1
                            continue
                        ts = datetime.now().strftime("%Y%m%d%H%M")
                        conflict = os.path.join(self.storage_path, f"CONFLICT_{ts}_{local_filename}")
                        os.rename(local_path, conflict)
                        print(f"[{self.get_ts()}] [!] Conflict detected on {local_filename}. Archiving.")
                        
                    # --- BATCH LIMIT CHECK ---
                    if remote_size > 0 and (current_batch_bytes + remote_size) > max_bytes:
                        print(f"[{self.get_ts()}] [BATCH] Threshold reached ({current_batch_bytes/(1024*1024):.1f}MB). Pausing sync.")
                        has_more_files = True
                        break # Break inner file loop

                    success = False
                    for attempt in range(1, 4):
                        try:
                            # Reconnect if socket died
                            try: ftp.voidcmd("NOOP")
                            except: 
                                print(f"[{self.get_ts()}] [!] Connection lost. Re-establishing...")
                                ftp = self._get_ftp(ip)
                                ftp.cwd(f'/DCIM/{folder}/')

                            print(f"[{self.get_ts()}] [*] [{name}]   -> Syncing: {filename} (Attempt {attempt})")
                            with open(local_path, 'wb') as f:
                                ftp.retrbinary(f"RETR {filename}", f.write)
                            
                            success = True
                            download_count += 1
                            if remote_size > 0: current_batch_bytes += remote_size
                            time.sleep(1) # Pacing delay after success
                            break 
                        except Exception as file_err:
                            print(f"[{self.get_ts()}] [!] Attempt {attempt} failed for {filename}: {file_err}")
                            if os.path.exists(local_path):
                                os.remove(local_path) # KILL FRAGMENT
                            if attempt < 3: time.sleep(2)
                    
                    if not success:
                        print(f"[{self.get_ts()}] [X] [{name}] Permanent failure on {filename}. Skipping.")

                ftp.cwd('/DCIM/')

            print(f"[{self.get_ts()}] [*] [{name}] SYNC COMPLETE: {download_count} new ({current_batch_bytes/(1024*1024):.1f} MB), {skip_count} skipped.")
            if ftp: ftp.quit()
            return has_more_files
            
        except Exception as e:
            print(f"[{self.get_ts()}] [!] Sync Error: {e}")
            return False # Assume fatal constraint
        finally:
            print(f"[{self.get_ts()}] [*] [{name}] HTTP: Sending Kill Switch...")
            try: requests.get(f"{base_url}/?custom=1&cmd=9018", timeout=1)
            except: pass
