import os
import random
import time
import subprocess
import glob
from datetime import datetime

# Global Constants
TARGET_DIR = "/home/kickit2/gemini/antigravity/scratch/deer_pics"
EXIFTOOL_PATH = "/home/kickit2/gemini/antigravity/scratch/tools/exiftool"
MULE_IDS = ["0A0038", "0A5F79", "0AC4CB"]

def generate_random_past_date(max_days_ago=3):
    """Generates a random Exif-formatted date string within the last N days."""
    now = time.time()
    random_seconds_ago = random.randint(0, max_days_ago * 24 * 3600)
    target_time = now - random_seconds_ago
    return datetime.fromtimestamp(target_time).strftime('%Y:%m:%d %H:%M:%S')

def forge_telemetry():
    if not os.path.isdir(TARGET_DIR):
        print(f"[!] Target directory {TARGET_DIR} does not exist. Please verify the folder name.")
        return
        
    avif_files = glob.glob(os.path.join(TARGET_DIR, "*.[aA][vV][iI][fF]"))
    
    if not avif_files:
        print(f"[-] No AVIF files found in {TARGET_DIR}.")
        return
        
    print(f"[+] Found {len(avif_files)} true AVIF files. Initiating Telemetry Forgery Sequence...")
    
    for count, original_path in enumerate(avif_files, start=1):
        # 1. Forge EXIF Timestamps
        fake_date = generate_random_past_date()
        print(f"  -> [{count}/{len(avif_files)}] Injecting EXIF DateTimeOriginal: {fake_date} into {os.path.basename(original_path)}")
        
        try:
            subprocess.run(
                [EXIFTOOL_PATH, f"-AllDates={fake_date}", "-overwrite_original", original_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"      [ERROR] ExifTool failed on {original_path}: {e}")
            continue

        # 2. Forge Hardware MAC Prefix (Rename File)
        mule_id = random.choice(MULE_IDS)
        img_sequence = random.randint(1000, 9999)
        new_filename = f"{mule_id}_IMG{img_sequence}.AVIF"
        new_filepath = os.path.join(TARGET_DIR, new_filename)
        
        # Rare collision check
        if os.path.exists(new_filepath):
            new_filename = f"{mule_id}_IMG{img_sequence}_{random.randint(10,99)}.AVIF"
            new_filepath = os.path.join(TARGET_DIR, new_filename)
            
        os.rename(original_path, new_filepath)
        print(f"      [OK] Re-assigned Hardware Source: {new_filename}")

    print(f"\n[SUCCESS] {len(avif_files)} images have been successfully deep-forged. They are ready.")

if __name__ == "__main__":
    forge_telemetry()
