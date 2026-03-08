import serial
import time
import os
import sys

def deploy(local, remote):
    print(f"Deploying {local} to {remote}...")
    ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
    # Wake up
    ser.write(b'\n\n')
    time.sleep(1)
    
    out = ser.read_all().decode('utf-8', errors='replace')
    sys.stdout.write(out)
    
    if 'login:' in out.lower():
        ser.write(b'kickit2\n')
        time.sleep(0.5)
        ser.write(b'test\n')
        time.sleep(1)
        out = ser.read_all().decode('utf-8', errors='replace')
        sys.stdout.write(out)

    with open(local, 'rb') as f:
        data = f.read()
    
    import base64
    b64_data = base64.b64encode(data).decode('utf-8')
    
    print(f"Deploying {local} to {remote}...")
    ser.write(f"base64 -d << 'INNER_EOF' > {remote}\n".encode())
    time.sleep(0.5)
    
    chunk_size = 512
    for i in range(0, len(b64_data), chunk_size):
        ser.write((b64_data[i:i+chunk_size]).encode())
        time.sleep(0.05)
        
    ser.write(b"\nINNER_EOF\n")
    time.sleep(1)
    ser.write(f"ls -l {remote}\n".encode())
    time.sleep(1)
    print(ser.read_all().decode('utf-8', errors='replace'))
    ser.close()

if __name__ == '__main__':
    deploy('MuleCommander/uploader.py', '/home/kickit2/MuleCommander/uploader.py')
