import serial
import time
import sys
import re
import os
import glob

PROMPT_REGEX = r"(\$|#|.+@.+:.*[\$#])\s*$"

def wait_for_prompt(ser, timeout=30):
    buffer = ""
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        if ser.in_waiting > 0:
            chunk = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
            buffer += chunk
            sys.stdout.write(chunk)
            sys.stdout.flush()
            if re.search(PROMPT_REGEX, buffer):
                return True
        time.sleep(0.1)
    return False

def main():
    print("Opening /dev/ttyACM1...")
    ser = serial.Serial('/dev/ttyACM1', 115200, timeout=1)
    
    ser.write(b'\n\n')
    time.sleep(1)
    
    out = ser.read_all().decode('utf-8', errors='replace')
    sys.stdout.write(out)
    
    if 'login:' in out.lower():
        print("Sending login...")
        ser.write(b'kickit2\n')
        time.sleep(0.5)
        ser.write(b'test\n')
        time.sleep(1)
        out = ser.read_all().decode('utf-8', errors='replace')
        sys.stdout.write(out)
        
    # Ctrl+C to drop any running python process from last time, just to be safe.
    ser.write(b'\x03\n\n')
    wait_for_prompt(ser, 5)
    
    commands = [
        "sudo rm -rf ~/OldMuleCommander",
        "mv ~/MuleCommander ~/OldMuleCommander 2>/dev/null",
        "rm -rf ~/MuleCommander",
        "mkdir ~/MuleCommander",
        "cd ~/MuleCommander",
        "python3 -m venv .venv",
        "source .venv/bin/activate",
        "sudo rfkill unblock wifi",
        "sleep 10",
        "pip install spidev smbus2 RPi.GPIO requests pexpect pillow pillow-avif-plugin piexif digi-xbee"
    ]
    
    for cmd in commands:
        print(f"\n[Running] {cmd}")
        ser.write((cmd + "\n").encode('utf-8'))
        # pip install takes a long time
        if "pip install" in cmd or "venv" in cmd:
            wait_for_prompt(ser, 180)
        else:
            wait_for_prompt(ser, 10)
            
    # Now deploy the files
    import base64
    local_files = glob.glob('/home/kickit2/gemini/antigravity/scratch/MuleCommander/*.py')
    for local_path in local_files:
        filename = os.path.basename(local_path)
        remote_path = f"/home/kickit2/MuleCommander/{filename}"
        
        print(f"\nDeploying {filename} (Aggressive Throttle Base64 Decoder)...")
        with open(local_path, 'rb') as f:
            encoded_content = base64.b64encode(f.read()).decode('utf-8')
            
        cmd_start = f'python3 -c "import sys, base64; open(\'{remote_path}\', \'wb\').write(base64.b64decode(sys.stdin.read()))" << \'EOF\''
        ser.write((cmd_start + "\n").encode('utf-8'))
        time.sleep(1.0) # Wait for python to start
        
        chunk_size = 32 # Exceedingly small for fragile serial buffers
        for i in range(0, len(encoded_content), chunk_size):
            chunk = encoded_content[i:i+chunk_size]
            ser.write((chunk + "\n").encode('utf-8'))
            time.sleep(0.25) # 250ms per 32 chars = extremely slow but extremely safe
            
        ser.write(b"EOF\n")
        time.sleep(2.0)
        wait_for_prompt(ser, 10)

    print("\n--- Finished Reprovisioning ---")
    ser.close()

if __name__ == "__main__":
    main()
