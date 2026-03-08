import spidev
import time
import RPi.GPIO as GPIO
import threading
import queue

class XBeeSPI:
    def __init__(self, bus=0, device=0, attn_pin=25, reset_pin=17):
        """
        Initialize SPI connection to XBee.
        attn_pin is the BCM GPIO pin connected to XBee /ATTN (Pin 19 / DIO1).
        reset_pin is the BCM GPIO pin connected to XBee /RESET (Pin 5).
        """
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(bus, device) # CE0
            self.spi.max_speed_hz = 3000000 # 3 MHz
            self.spi.mode = 0 # CPOL=0, CPHA=0
        except FileNotFoundError:
            print("SPI not found. Did you enable it in raspi-config?")
            raise
        
        self.attn_pin = attn_pin
        self.reset_pin = reset_pin
        self.spi_lock = threading.Lock()
        self.rx_queue = queue.Queue()
        
        GPIO.setmode(GPIO.BCM)
        # XBee pulls /ATTN low when it has data ready for the host.
        # Ensure the internal pull-up resistor is enabled on the Pi.
        if self.attn_pin is not None:
            GPIO.setup(self.attn_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            try:
                GPIO.add_event_detect(self.attn_pin, GPIO.FALLING, callback=self._attn_isr)
            except RuntimeError as e:
                print(f"Warning: Failed to add edge detection for /ATTN pin: {e}. Falling back to passive polling.")
        if self.reset_pin is not None:
            GPIO.setup(self.reset_pin, GPIO.OUT)
            GPIO.output(self.reset_pin, GPIO.HIGH) # Active low reset

    def hardware_reset(self):
        """Asserts the /RESET line low to reboot the XBee and clear any SPI framing locks."""
        if self.reset_pin is not None:
            print(f"Asserting /RESET on GPIO {self.reset_pin}...")
            GPIO.output(self.reset_pin, GPIO.LOW)
            time.sleep(0.5)
            GPIO.output(self.reset_pin, GPIO.HIGH)
            time.sleep(1.0) # Wait for XBee to boot and initialize
            print("Clocking pad bytes to sync SPI peripheral...")
            try:
                with self.spi_lock:
                    self.spi.xfer2([0x00] * 1000)
            except Exception as e:
                print(f"Padding failed (normal on initial boot): {e}")
            time.sleep(0.5)

    def close(self):
        self.spi.close()
        GPIO.cleanup()

    def build_transmit_request(self, dest_64: bytes, dest_16: bytes, rf_data: bytes, frame_id=0x00) -> list:
        """Builds a raw API Mode 1 (0x10) Transmit Request Frame"""
        frame_type = 0x10
        radius = 0x00
        options = 0x00
        
        # Frame Data Payload (Checksum is calculated ONLY over this)
        frame_data = [frame_type, frame_id] + list(dest_64) + list(dest_16) + [radius, options] + list(rf_data)
        checksum = 0xFF - (sum(frame_data) & 0xFF)
        
        length = len(frame_data)
        return [0x7E, (length >> 8) & 0xFF, length & 0xFF] + frame_data + [checksum]

    def build_at_command(self, command: str, parameter: bytes = b'', frame_id=0x01) -> list:
        """Builds a Local AT Command Request (0x08) to configure/query the XBee"""
        frame_type = 0x08
        cmd_bytes = [ord(c) for c in command]
        
        frame_data = [frame_type, frame_id] + cmd_bytes + list(parameter)
        checksum = 0xFF - (sum(frame_data) & 0xFF)
        
        length = len(frame_data)
        return [0x7E, (length >> 8) & 0xFF, length & 0xFF] + frame_data + [checksum]

    def xfer2(self, data):
        """Thread-safe generic SPI transfer."""
        with self.spi_lock:
            return self.spi.xfer2(data)

    def _attn_isr(self, channel):
        """Interrupt Service Routine for /ATTN falling edge"""
        # Over-provision read buffer to ensure full packet capture
        with self.spi_lock:
            data = self.spi.xfer2([0x00] * 512)
        
        # Strip all SPI padding (0x00 and 0xFF) that occurs *between* frames
        # Wait, 0x00 can be valid payload data! We can't globally strip it.
        # We must seek 0x7E, then read exactly that length.
        
        i = 0
        found_bytes = False
        while i < len(data) - 4:
            if data[i] == 0x7E:
                length = (data[i+1] << 8) | data[i+2]
                total_frame_size = length + 4 # 1(0x7E) + 2(Len) + Payload + 1(CSUM)
                
                # If we have enough bytes in this chunk
                if i + total_frame_size <= len(data):
                    frame = data[i : i + total_frame_size]
                    self.rx_queue.put(bytearray(frame))
                    # print(f"SPI Rx: {[hex(x) for x in frame]}") # Debug
                    i += total_frame_size
                    found_bytes = True
                    continue
                else:
                    # Packet spans across chunks. Not handling partials yet.
                    pass
            i += 1
            
        if not found_bytes:
            # We polled 512 bytes but found no valid 0x7E frame!
            # Could mean the XBee is holding /ATTN low despite empty buffer, or we missed alignment.
            print("SPI DIAGNOSTIC: Clocked 512 bytes but found NO 0x7E frame! /ATTN may be stuck low, starring XBee CPU!")

    def read_available(self) -> list:
        # Passive polling fallback using lightweight GPIO instead of blinding the SPI bus
        # Removed manual _attn_isr(0) invocation; strictly rely on the hardware falling-edge queue now.
        if self.attn_pin is not None and GPIO.input(self.attn_pin) == GPIO.LOW:
            self._attn_isr(0)
             
        frames = []
        while not self.rx_queue.empty():
            try:
                frames.append(self.rx_queue.get_nowait())
            except queue.Empty:
                break
        return frames

    def parse_frame(self, frame_bytes):
        """Extracts RF data or AT command response from an API frame."""
        if not frame_bytes or len(frame_bytes) < 4 or frame_bytes[0] != 0x7E:
            return None
        
        frame_type = frame_bytes[3]
        
        if frame_type == 0x90: # Receive Packet
            src_64 = bytes(frame_bytes[4:12])
            src_16 = bytes(frame_bytes[12:14])
            rf_data = bytes(frame_bytes[15:-1])
            return {'type': 'rx', 'src_64': src_64, 'src_16': src_16, 'data': rf_data}
        elif frame_type == 0x88: # AT Command Response
            frame_id = frame_bytes[4]
            try:
                command = bytes(frame_bytes[5:7]).decode('ascii')
            except UnicodeDecodeError:
                command = "UNKNOWN"
            status = frame_bytes[7]
            data = bytes(frame_bytes[8:-1])
            return {'type': 'at_response', 'frame_id': frame_id, 'command': command, 'status': status, 'data': data}
        elif frame_type == 0x8B: # Transmit Status
            if len(frame_bytes) >= 10:
                return {'type': 'tx_status', 'frame_id': frame_bytes[4], 'status': frame_bytes[8]}
            
        return {'type': 'unknown', 'frame_type': frame_type}

    def blast_data(self, dest_64: bytes, dest_16: bytes, raw_payload: bytes, frame_id=0):
        """Builds and transfers the frame over SPI."""
        frame = self.build_transmit_request(dest_64, dest_16, raw_payload, frame_id=frame_id)
        with self.spi_lock:
            self.spi.xfer2(frame)
