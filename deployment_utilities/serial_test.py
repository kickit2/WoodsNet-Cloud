import serial, time
s = serial.Serial('/dev/ttyACM1', 115200, timeout=1)
s.write(b'\n\n')
time.sleep(1)
s.read_all() # clear buffer
s.write(b'ls -la /home/kickit2/MuleCommander/\n')
time.sleep(2)
out = s.read_all().decode(errors='replace')
with open('serial_out.txt', 'w') as f:
    f.write(out)
s.close()
