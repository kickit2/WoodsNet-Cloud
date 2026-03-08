import serial, time
s = serial.Serial('/dev/ttyACM1', 115200, timeout=1)
s.write(b'\x03\x03\x03\r\n\r\n')
time.sleep(2)
s.read_all()
s.write(b'echo "UART ALIVE"\r\n')
time.sleep(1)
out = s.read_all().decode(errors='replace')
with open('serial_out2.txt', 'w') as f:
    f.write(out)
s.close()
