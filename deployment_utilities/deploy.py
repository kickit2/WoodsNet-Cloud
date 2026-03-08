import argparse
import time
import os
import sys
# Reuse our serial logic? Or duplicate simple version?
# Let's import SerialShell if possible, or copy-paste core logic for standalone use.
# Since serial_commander.py is in faux_base/, let's assume we run from root or copy.
# We'll make this standalone for robustness.

import serial
import re

PROMPT_REGEX = r"(\$|#|.+@.+:.*[\$#])\s*$"

class SerialDeployer:
    def __init__(self, port, baudrate):
        self.ser = serial.Serial(port, baudrate, timeout=5)
        
    def wait_for_prompt(self, timeout=10):
        buffer = ""
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='replace')
                buffer += chunk
                sys.stdout.write(chunk)
                sys.stdout.flush()
                if re.search(PROMPT_REGEX, buffer):
                    return True
            time.sleep(0.1)
        return False

    def send_command(self, cmd):
        self.ser.write((cmd + "\n").encode('utf-8'))
        time.sleep(0.1)

    def deploy_file(self, local_path, remote_path):
        if not os.path.exists(local_path):
            print(f"Error: Local file {local_path} not found.")
            return

        print(f"Deploying {local_path} -> {remote_path}...")
        
        # Wake up
        self.send_command("")
        self.wait_for_prompt(2)
        
        # Read file content
        with open(local_path, 'r') as f:
            content = f.read()
            
        # Using cat << 'EOF' > remote_path
        # We use 'EOF' (quoted) to prevent variable expansion if any $ exist in python code
        cmd_start = f"cat << 'EOF' > {remote_path}"
        self.send_command(cmd_start)
        
        # Send content in chunks to avoid buffer overflow
        chunk_size = 128
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i+chunk_size]
            self.ser.write(chunk.encode('utf-8'))
            time.sleep(0.05) # Throttle
            
        # Send EOF
        self.send_command("\nEOF")
        
        # Verify
        if self.wait_for_prompt(10):
            print(f"\n[+] Deployed {remote_path}")
            # Check size?
            self.send_command(f"ls -l {remote_path}")
            self.wait_for_prompt(2)
        else:
            print("\n[-] Timeout waiting for deployment confirmation")

    def close(self):
        self.ser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy file to Pi via Serial")
    parser.add_argument("local", help="Local file path")
    parser.add_argument("remote", help="Remote file path (absolute or relative to ~)")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial Port")
    
    args = parser.parse_args()
    
    deployer = SerialDeployer(args.port, 115200)
    try:
        deployer.deploy_file(args.local, args.remote)
    finally:
        deployer.close()
