import os
import time
import math
from pathlib import Path
from PIL import Image
import pillow_avif
from datetime import datetime

class ImageCrusher:
    def __init__(self, storage_path="/media/cam_grabs"):
        self.storage_path = storage_path
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

    def get_ts(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def resize_to_mp(self, img, target_mp):
        width, height = img.size
        current_mp = (width * height) / 1_000_000.0
        if current_mp <= target_mp:
            return img, current_mp

        ratio = math.sqrt(target_mp / current_mp)
        new_w, new_h = int(width * ratio), int(height * ratio)
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS), current_mp

    def crush(self, target_mp=3.0, quality=55, speed=11, delete_source=True):
        print(f"[{self.get_ts()}] [CRUSHER] Starting Smart Sweep ({target_mp}MP Target)...")
        base_path = Path(self.storage_path)
        jpg_files = sorted(list(base_path.glob("*.JPG")) + list(base_path.glob("*.jpg")))
        done, skipped = 0, 0

        for jpg_path in jpg_files:
            avif_path = jpg_path.with_suffix(".AVIF")
            if avif_path.exists():
                skipped += 1
                continue

            print(f"[{self.get_ts()}] [CRUSHER] Processing: {jpg_path.name}...")

            try:
                start_time = time.time()
                orig_size_kb = os.path.getsize(jpg_path) / 1024

                with Image.open(jpg_path) as img_raw:
                    orig_w, orig_h = img_raw.size
                    img, orig_mp = self.resize_to_mp(img_raw, target_mp)
                    
                    colors = img.getcolors(maxcolors=1000)
                    color_count = len(colors) if colors else 1001
                    is_gray = color_count <= 256
                    final_mode = "L" if is_gray else "RGB"
                    if is_gray:
                        img = img.convert("L")

                    # 1. Save the file
                    img.save(avif_path, "AVIF", quality=quality, speed=speed)

                # 2. VERIFY the file before reporting success
                try:
                    with Image.open(avif_path) as verify_img:
                        verify_img.verify() 
                    
                    # 3. Success Output
                    elapsed = time.time() - start_time
                    new_size_kb = os.path.getsize(avif_path) / 1024
                    compression = (1 - (new_size_kb / orig_size_kb)) * 100
                    
                    print(f"[{self.get_ts()}] [CRUSHER] Result for {jpg_path.name}:")
                    print(f"    >>> ORIG:  {orig_w}x{orig_h} ({orig_mp:.1f}MP) {orig_size_kb:.1f}KB")
                    print(f"    >>> CRUSH: {img.size[0]}x{img.size[1]} ({target_mp}MP) {new_size_kb:.1f}KB Mode: {final_mode}")
                    print(f"    >>> STATS: Ratio: {compression:.1f}% | Time: {elapsed:.2f}s | VERIFIED")

                    if delete_source and avif_path.exists():
                        os.remove(jpg_path)
                    done += 1

                except Exception as v_err:
                    print(f"[{self.get_ts()}] [!] [CRUSHER] VERIFICATION FAILED - DELETING: {avif_path.name}")
                    if avif_path.exists():
                        os.remove(avif_path)
                    # We don't increment 'done' here, so it effectively fails this file.

            except Exception as e:
                print(f"[{self.get_ts()}] [!] [CRUSHER] Critical Error on {jpg_path.name}: {e}")

        print(f"[{self.get_ts()}] [CRUSHER] Finished: {done} crushed and verified, {skipped} skipped.")
        return done
