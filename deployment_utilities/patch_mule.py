import serial
import time

def deploy_patch():
    try:
        ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1, write_timeout=2)
        # Force prompt
        ser.write(b'\x03\n\x03\n\n')
        time.sleep(1)
        ser.read_all()
        
        # Send Python script to execute on the Pi Zero to safely rewrite uploader.py
        patch_script = """python3 -c "
import re
with open('/home/kickit2/MuleCommander/uploader.py', 'r') as f:
    code = f.read()

# Patched Patch Block
new_block_patch = '''                    if not patch_success:
                        if not self.summary_mode:
                            print(\\"Failed to patch window after max attempts. Giving up and rewriting whole window.\\")
                        consecutive_failures += 1
                        
                        if consecutive_failures == 3 and pl < 4:
                            pl += 1
                            print(f\\'\\\\n[!] Mid-Stream Interference Detected: Bursting Power Level upwards to PL={pl}...\\\\n\\')
                            self.device.xfer(self.device.build_at_command(\\'PL\\', bytes([pl]), frame_id=12))
                            import time; time.sleep(0.02)
                            self.device.read_available()'''

# Patched Generic Block
new_block_generic = '''                else:
                    # Generic Timeout (Total RF wipeout) or TX Fail
                    consecutive_success = 0
                    consecutive_failures += 1
                    
                    if consecutive_failures == 3 and pl < 4:
                        pl += 1
                        print(f\\'\\\\n[!] Mid-Stream Silence Detected: Bursting Power Level upwards to PL={pl}...\\\\n\\')
                        self.device.xfer(self.device.build_at_command(\\'PL\\', bytes([pl]), frame_id=13))
                        import time; time.sleep(0.02)
                        self.device.read_available()'''


# Original Match Strings
old_block_patch = '''                    if not patch_success:
                        if not self.summary_mode:
                            print(\\"Failed to patch window after max attempts. Giving up and rewriting whole window.\\")
                        consecutive_failures += 1'''

old_block_generic = '''                else:
                    # Generic Timeout (Total RF wipeout) or TX Fail
                    consecutive_success = 0
                    consecutive_failures += 1
                    # self.pacing_offset = min(0.024, self.pacing_offset + 0.002)'''


code = code.replace(old_block_patch, new_block_patch)
code = code.replace(old_block_generic, new_block_generic)

with open('/home/kickit2/MuleCommander/uploader.py', 'w') as f:
    f.write(code)
print('PATCH_SUCCESS')
"
"""
        print("Sending patch payload...")
        ser.write(patch_script.encode('utf-8'))
        time.sleep(2)
        print(ser.read_all().decode('utf-8', errors='ignore'))
        ser.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    deploy_patch()
