import serial
import time
import sys
import re

def trigger_mule():
    print("Opening /dev/ttyACM0...")
    ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
    
    # Wake up the terminal
    ser.write(b'\n\n')
    time.sleep(1)
    
    out = ser.read_all().decode('utf-8', errors='replace')
    sys.stdout.write(out)
    sys.stdout.flush()
    
    # Handle Login if necessary
    if 'login:' in out.lower():
        print("Sending login...")
        ser.write(b'kickit2\n')
        time.sleep(0.5)
        ser.write(b'test\n')
        time.sleep(1)
        out = ser.read_all().decode('utf-8', errors='replace')
        sys.stdout.write(out)
        sys.stdout.flush()
        
    print("Clearing old python processes...")
    ser.write(b'sudo killall python3\n')
    time.sleep(2)
    ser.read_all() # flush
    
    print("Executing Fleet Manager full pipeline via Basic_Wifi_Bt_Test env...")
    ser.write(b'cd ~/MuleCommander && source ~/Basic_Wifi_Bt_Test/bin/activate && sudo /home/kickit2/Basic_Wifi_Bt_Test/bin/python3 -u fleet_manager.py\n')
    
    start = time.time()
    try:
        # Stream the output for 300 seconds for full pipeline execution
        while time.time() - start < 300:
            if ser.in_waiting:
                chunk = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
                sys.stdout.write(chunk)
                sys.stdout.flush()
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nManually interrupted.")
    finally:
        ser.write(b'\x03') # Ctrl+C to kill if running
        time.sleep(1)
        ser.close()
        print("\nSerial connection closed.")

if __name__ == "__main__":
    trigger_mule()
