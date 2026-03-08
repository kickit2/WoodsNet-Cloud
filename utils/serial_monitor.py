import serial
import time
import sys
import threading

def read_from_port(ser):
    while True:
        try:
            line = ser.readline()
            if line:
                sys.stdout.buffer.write(line)
                sys.stdout.flush()
        except serial.SerialException:
            break

try:
    print("Opening /dev/ttyACM1...")
    ser = serial.Serial('/dev/ttyACM1', 115200, timeout=0.1)
    
    # Start reader thread
    thread = threading.Thread(target=read_from_port, args=(ser,))
    thread.daemon = True
    thread.start()

    # Clear prompt
    ser.write(b'\n\n')
    time.sleep(0.5)
    ser.write(b'\x03\n') # ctrl c
    time.sleep(0.5)

    print("Sending target launch command...")
    cmd = b'sudo rfkill unblock all; sleep 5; cd ~/MuleCommander && source .venv/bin/activate && python3 -u uploader.py\r\n'
    ser.write(cmd)

    # Keep alive to monitor
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\nExiting...")
    ser.close()
except Exception as e:
    print(f"Error: {e}")
