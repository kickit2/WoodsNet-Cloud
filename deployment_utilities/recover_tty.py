import serial, time
s = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
# Send EOF, INNER_EOF, and Ctrl+C, Ctrl+D
s.write(b'\nINNER_EOF\nINNER_EOF\n\x04\x04\x03\x03\n')
time.sleep(1)
s.read_all() # clear buffer
s.write(b'\nls -la /home/kickit2/MuleCommander/\n')
time.sleep(1)
out = s.read_all().decode(errors='replace')
with open('serial_out3.txt', 'w') as f:
    f.write(out)
s.close()
