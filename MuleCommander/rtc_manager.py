import time
from datetime import datetime

class RTCManager:
    """
    User-space I2C driver for the DS3231 Real-Time Clock.
    Communicates directly via smbus2 on i2c-1 (0x68) to avoid needing sudo/hwclock.
    """
    DS3231_I2C_ADDR = 0x68

    def __init__(self, bus_number=1):
        self.bus_number = bus_number
        try:
            import smbus2
            self.bus = smbus2.SMBus(self.bus_number)
            self.enabled = True
        except ImportError:
            print("[RTC] smbus2 module missing. Falling back to stub.")
            self.enabled = False
        except Exception as e:
            print(f"[RTC] I2C bus {bus_number} unavailable: {e}")
            self.enabled = False

    def _dec_to_bcd(self, val):
        return (val // 10 << 4) + (val % 10)

    def _bcd_to_dec(self, val):
        return (val >> 4) * 10 + (val & 0x0F)

    def set_time(self, ts):
        """
        Sets the DS3231 registers (0x00 - 0x06) to the matched Unix timestamp.
        """
        if not self.enabled: return False
        
        dt = datetime.fromtimestamp(ts)
        
        # DS3231 registers: [Seconds, Minutes, Hours, Day, Date, Month, Year(0-99)]
        # We start at register 0x00
        data = [
            self._dec_to_bcd(dt.second),
            self._dec_to_bcd(dt.minute),
            self._dec_to_bcd(dt.hour),
            self._dec_to_bcd(dt.isoweekday()), # 1(Mon) to 7(Sun)
            self._dec_to_bcd(dt.day),
            self._dec_to_bcd(dt.month),
            self._dec_to_bcd(dt.year % 100)
        ]
        
        try:
            self.bus.write_i2c_block_data(self.DS3231_I2C_ADDR, 0x00, data)
            print(f"[RTC] Time set to {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            return True
        except Exception as e:
            print(f"[RTC] I2C Write Error: {e}")
            return False

    def get_time(self):
        """
        Reads the DS3231 registers and returns a Unix timestamp.
        """
        if not self.enabled: return 0
        
        try:
            data = self.bus.read_i2c_block_data(self.DS3231_I2C_ADDR, 0x00, 7)
            
            second = self._bcd_to_dec(data[0])
            minute = self._bcd_to_dec(data[1])
            hour   = self._bcd_to_dec(data[2] & 0x3F) # Strip 12/24h bits
            day    = self._bcd_to_dec(data[4])
            month  = self._bcd_to_dec(data[5] & 0x7F) # Strip century bit
            year   = self._bcd_to_dec(data[6]) + 2000
            
            dt = datetime(year, month, day, hour, minute, second)
            return int(dt.timestamp())
        except Exception as e:
            print(f"[RTC] I2C Read Error: {e}")
            return 0
            
    def set_wakeup_alarm(self, seconds_from_now):
        """
        Programs Alarm 1 (Registers 0x07 - 0x0A) to trigger the INT pin.
        This sends a LOW signal to the ATtiny84 to wake up the rig.
        """
        if not self.enabled: return False
        
        target_ts = self.get_time() + seconds_from_now
        dt = datetime.fromtimestamp(target_ts)
        
        # Alarm 1 format: [Sec, Min, Hour, Day/Date]
        # We need to set the match bits (A1M1-A1M4) to match exactly on Date, Hour, Min, Sec
        # That means bit 7 of all four registers must be 0
        
        try:
            # 1. Clear control flags so Alarm 1 doesn't fire while we configure it
            ctrl = self.bus.read_byte_data(self.DS3231_I2C_ADDR, 0x0E)
            self.bus.write_byte_data(self.DS3231_I2C_ADDR, 0x0E, ctrl & ~0x01) # Disable A1IE
            
            # 2. Clear Alarm 1 Flag in status register (0x0F)
            status = self.bus.read_byte_data(self.DS3231_I2C_ADDR, 0x0F)
            self.bus.write_byte_data(self.DS3231_I2C_ADDR, 0x0F, status & ~0x01) # Clear A1F

            # 3. Write Target Time with Match Bits = 0 (Match on Date/Hr/Min/Sec)
            data = [
                self._dec_to_bcd(dt.second) & 0x7F,
                self._dec_to_bcd(dt.minute) & 0x7F,
                self._dec_to_bcd(dt.hour) & 0x7F, # 24hr format
                self._dec_to_bcd(dt.day) & 0x3F   # Match on Date, not Day-of-week
            ]
            self.bus.write_i2c_block_data(self.DS3231_I2C_ADDR, 0x07, data)
            
            # 4. Enable INTCN (Interrupt Control) and A1IE (Alarm 1 Enable)
            ctrl = self.bus.read_byte_data(self.DS3231_I2C_ADDR, 0x0E)
            ctrl |= 0x04 # INTCN = 1 (Route alarms to INT pin)
            ctrl |= 0x01 # A1IE  = 1 (Enable Alarm 1)
            self.bus.write_byte_data(self.DS3231_I2C_ADDR, 0x0E, ctrl)
            
            print(f"[RTC] Wake-up Alarm set for {dt.strftime('%H:%M:%S')} ({seconds_from_now}s)")
            return True
            
        except Exception as e:
            print(f"[RTC] Alarm Set Error: {e}")
            return False
