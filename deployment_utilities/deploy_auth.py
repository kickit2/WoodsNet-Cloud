import argparse, time, sys, serial, re

PROMPT_REGEX = r"(\$|#|.+@.+:.*[\$#])\s*$"

class SerialDeployer:
    def __init__(self, port, baudrate):
        self.ser = serial.Serial(port, baudrate, timeout=1)
        
    def wait_for_prompt(self, timeout=10):
        buffer = ""
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='replace')
                buffer += chunk
                sys.stdout.write(chunk)
                sys.stdout.flush()
                if re.search(PROMPT_REGEX, buffer): return True
                if "login:" in buffer.lower():
                    print("\n[Auth] Triggering Login...")
                    self.ser.write(b'kickit2\n')
                    time.sleep(0.5)
                    self.ser.write(b'test\n')
                    time.sleep(1)
                    buffer = ""
            time.sleep(0.1)
        return False

    def send_command(self, cmd):
        self.ser.write((cmd + "\n").encode('utf-8'))
        time.sleep(0.1)

    def deploy_file(self, local_path, remote_path):
        print(f"\nDeploying {local_path} -> {remote_path}...")
        self.send_command("")
        self.wait_for_prompt(5)
        
        with open(local_path, 'r') as f: content = f.read()
            
        self.send_command(f"cat << 'INNER_EOF' > {remote_path}")
        chunk_size = 128
        for i in range(0, len(content), chunk_size):
            self.ser.write(content[i:i+chunk_size].encode('utf-8'))
            time.sleep(0.05)
            
        self.send_command("\nINNER_EOF")
        if self.wait_for_prompt(5):
            print(f"\n[+] Deployed {remote_path}")
        else:
            print("\n[-] Timeout")
            
deployer = SerialDeployer('/dev/ttyACM1', 115200)
try:
    deployer.deploy_file('MuleCommander/mule_protocol.py', '/home/kickit2/MuleCommander/mule_protocol.py')
    deployer.deploy_file('MuleCommander/uploader.py', '/home/kickit2/MuleCommander/uploader.py')
    deployer.deploy_file('MuleCommander/fleet_manager.py', '/home/kickit2/MuleCommander/fleet_manager.py')
finally:
    deployer.ser.close()
