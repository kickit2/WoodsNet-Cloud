import time
import spidev
import RPi.GPIO as GPIO

# Manually override RESET High
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.OUT)
GPIO.output(17, GPIO.HIGH)

spi = spidev.SpiDev()
spi.open(0,0)
spi.max_speed_hz = 1000000
spi.mode = 0

print("Raw SPI dumping initialized. Waiting for packets...")
try:
    for _ in range(50):
        # We write 0x00 to clock the MISO
        res = spi.xfer2([0x00] * 64)
        if any(x != 0xFF for x in res):
            print("DATA DETECTED:")
            print([hex(x) for x in res])
        time.sleep(0.3)
except KeyboardInterrupt:
    pass
finally:
    spi.close()
    GPIO.cleanup()
