import time
import os
import struct
import rtc_manager
import api_client
from mule_protocol import Packet, PacketType, calculate_crc16, BaseActions
# Constants
BLAST_DATA_HEADER = 0xAA
# Max usable data chunk = 256 (total frame) - 18 (API fixed) - 3 (our header/seq) = 235 bytes
BLAST_PAYLOAD_SIZE = 235
from xbee_spi import XBeeSPI

# Config
BASE_NODE_ID = 0xF  # Base Station ID
MY_NODE_ID = 0x5    # Example Mule ID

# META AI FIX: Expose empirical hardware scaling limit for easy calibration
EMPIRICAL_BASE_PACING = 0.014

BROADCAST_64 = b'\x00\x00\x00\x00\x00\x00\xFF\xFF'
BROADCAST_16 = b'\xFF\xFE'

class MuleUploader:
    def __init__(self, is_relay_mode=False, target_relay_id=0):
        # We rely entirely on xbee_spi now
        self.device = XBeeSPI(bus=0, device=0, attn_pin=25, reset_pin=17)
        self.device.hardware_reset()
        self.base_addr_64 = None
        self.base_addr_16 = None
        self.frame_id_counter = 1
        self.summary_mode = True
        self.pacing_offset = 0.014
        self.is_relay_mode = is_relay_mode
        self.target_relay_id = target_relay_id
        
    def start(self):
        print(f"Opening Mule XBee on SPI...")
        # Optional: Test communication by querying HV
        cmd = self.device.build_at_command("HV")
        self.device.xfer2(cmd)
        
        start = time.time()
        parsed = None
        while time.time() - start < 3:
            frames = self.device.read_available()
            for f in frames:
                p = self.device.parse_frame(f)
                if p and p.get('type') == 'at_response':
                    parsed = p
                    break
            if parsed:
                break
            time.sleep(0.02)
        
        if parsed and parsed.get('type') == 'at_response' and parsed.get('command') == 'HV':
            print("XBee SPI Validated (Hardware Version Received).")
        else:
            print("Warning: Initial SPI query failed or timed out. Handshake may fail.")
            
        # Enforce Volatile Parameters deleted by Hardware Reset
        print("Enforcing 200 Kbps Volatile Data Rate (TR=1) and Power Level (PL=0)...")
        self.device.xfer2(self.device.build_at_command("TR", b'\x01', frame_id=2))
        time.sleep(0.02)
        self.device.read_available() # Flush TR response
        
        print("Querying Maximum Network Payload (NP) for diagnostic logging...")
        # Hardware Maximum Transmission Unit (MTU) Probe
        self.device.xfer2(self.device.build_at_command("NP", frame_id=3))
        time.sleep(0.02)
        for f in self.device.read_available():
            parsed = self.device.parse_frame(bytearray(f))
            if parsed and parsed.get('command') == 'NP':
                print(f"Hardware confirms MAX Network Payload limit: {int.from_bytes(parsed['data'], 'big')} bytes.")
        
        self.device.xfer2(self.device.build_at_command("PL", b'\x00', frame_id=4))
        time.sleep(0.02)
        self.device.read_available() # Flush PL response
        
    def execute_prime_shutdown(self, sleep_duration=7200):
        print("\n--- INITIATING PRIME SHUTDOWN ROUTINE ---")
        try:
            # Revert to 10k lane
            self.device.xfer2(self.device.build_at_command("BR", b'\x00', frame_id=20))
            time.sleep(0.05)
            # Control ID
            self.device.xfer2(self.device.build_at_command("ID", struct.pack('>H', 0x1010), frame_id=21))
            time.sleep(0.05)
            # Sleep settings
            self.device.xfer2(self.device.build_at_command("SM", b'\x04', frame_id=22))
            time.sleep(0.05)
            self.device.xfer2(self.device.build_at_command("SP", struct.pack('>H', 0x2EE0), frame_id=23))
            time.sleep(0.05)
            self.device.xfer2(self.device.build_at_command("ST", struct.pack('>H', 0x07D0), frame_id=24))
            time.sleep(0.05)
            
            # Phase 13: Time-Division Multiplexed Power Management
            # The Pi sets the wake alarm directly on the DS3231 RTC.
            print(f"[RTC] Setting DS3231 Wake Alarm for {sleep_duration} seconds from now...")
            try:
                from rtc_manager import RTCManager
                rtc = RTCManager()
                rtc.set_wakeup_alarm(sleep_duration)
            except Exception as e:
                print(f"[RTC] Failed to set DS3231 alarm: {e}")
            
            # The ATtiny is "stupid" - it relies on the Pi to tell it to sleep,
            # and relies on the RTC's INT pulling low to wake it up.
            print(f"[I2C] Commanding ATtiny84 to drop P-Channel Mosfet and cut main power...")
            # e.g., i2c_bus.write_byte_data(0x08, 0x02, 0x01)
            
        except Exception as e:
            print(f"Error during Prime Routine: {e}")
        
        print("\n[OS] Executing safe system halt...")
        import os
        import sys
        # os.system('sudo shutdown -h now')
        sys.exit(0)

    def negotiate_state_machine(self, timeout=10.0):
        print("\n--- SESSION STATE MACHINE: WAKING ---")
        
        # STATE 1: INITIALIZATION
        print("STATE 1: INITIALIZATION")
        heartbeat_payload = bytes([0x64, 0x00]) # Example: Mule_V=100 (5V), Cam_Status=0
        hb_pkt = Packet(BASE_NODE_ID, MY_NODE_ID, PacketType.HEARTBEAT, heartbeat_payload)
        
        retries = 3
        ssack_received = False
        while retries > 0 and not ssack_received:
            print("Sending TYPE 6: HEARTBEAT")
            self.broadcast_packet(PacketType.HEARTBEAT, heartbeat_payload)
            
            # Wait for SSACK
            start = time.time()
            while time.time() - start < 3.0:
                frames = self.device.read_available()
                for frame in frames:
                    parsed = self.device.parse_frame(frame)
                    if parsed and parsed.get('type') == 'rx':
                        pkt = Packet.from_bytes(parsed['data'])
                        if pkt and pkt.msg_type == PacketType.SSACK:
                            self.base_addr_64 = parsed['src_64']
                            self.base_addr_16 = parsed.get('src_16', BROADCAST_16)
                            print(f"Received Base SSACK! Locked Route: {self.base_addr_64.hex()}")
                            ssack_received = True
                            break
                if ssack_received:
                    break
                time.sleep(0.05)
                
            retries -= 1
            if not ssack_received and retries > 0:
                print("HEARTBEAT Timeout. Retrying...")
                
        if not ssack_received:
            print("CRITICAL: Failed to initialize session with Target. Aborting.")
            return False
            
        # STATE 2 & 3: SOLICITATION AND EXECUTION
        while True:
            print("\nSTATE 2: TASK SOLICITATION")
            print("Sending TYPE 7: TASK_QUERY")
            self.device.xfer2(self.device.build_transmit_request(self.base_addr_64, self.base_addr_16, Packet(BASE_NODE_ID, MY_NODE_ID, PacketType.TASK_QUERY, b'').to_bytes()))
            
            # Wait for TASK_ASSIGN
            start = time.time()
            assigned_task = None
            assigned_token = None
            while time.time() - start < 4.0:
                frames = self.device.read_available()
                for frame in frames:
                    parsed = self.device.parse_frame(frame)
                    if parsed and parsed.get('type') == 'rx':
                        pkt = Packet.from_bytes(parsed['data'])
                        if pkt and pkt.msg_type == PacketType.TASK_ASSIGN:
                            if len(pkt.payload) >= 2:
                                assigned_task = pkt.payload[0]
                                assigned_token = pkt.payload[1]
                                try:
                                    task_name = BaseActions(assigned_task).name
                                except ValueError:
                                    task_name = f"UNKNOWN (0x{assigned_task:02X})"
                                print(f"Received Base TASK_ASSIGN: Action {task_name}")
                                break
                if assigned_task is not None:
                    break
                time.sleep(0.05)
                
            if assigned_task is None:
                print("TASK_QUERY Timeout. Retrying...")
                continue
                
            if assigned_task == BaseActions.NO_TASK:
                print("\nSTATE 4: YIELD & UPLOAD DECISION")
                print("Base reports NO_TASK (0x09). Yielding to internal Mule architecture...")
                break # Return to upload logic
                
            else:
                print(f"\nSTATE 3: EXECUTION & REPORTING")
                
                status_code = 0x00 # SUCCESS
                resp_data = b''
                
                if assigned_task == BaseActions.SYNC_TIME:
                    # Payload is Action(1) Token(1) Len(1) Timestamp(4)
                    print(f"DEBUG: SYNC_TIME Payload Raw: {pkt.payload.hex()} (Len: {len(pkt.payload)})")
                    if len(pkt.payload) >= 7:
                        ts = struct.unpack('>I', bytes(pkt.payload[3:7]))[0]
                        print(f"Executing SYNC_TIME: Setting Pi clock to {ts}")
                        try:
                            from rtc_manager import RTCManager
                            rtc = RTCManager()
                            if rtc.set_time(ts):
                                resp_data = struct.pack('>I', ts) # Echo back
                            else:
                                status_code = 0x01
                        except Exception as e:
                            print(f"Failed to set time: {e}")
                            status_code = 0x01 # FAIL
                    else:
                         status_code = 0x01 # FAIL (Missing Data)

                elif assigned_task == BaseActions.GET_NODE_RSSI:
                    print("Executing GET_NODE_RSSI: Querying XBee ATDB...")
                    self.device.xfer2(self.device.build_at_command("DB", frame_id=30))
                    start_db = time.time()
                    rssi = None
                    while time.time() - start_db < 1.0:
                        db_frames = self.device.read_available()
                        for f in db_frames:
                            p = self.device.parse_frame(f)
                            if p and p.get('type') == 'at_response' and p.get('command') == 'DB':
                                if len(p.get('data', b'')) >= 1:
                                    rssi = p['data'][0]
                                    break
                        if rssi is not None:
                            break
                        time.sleep(0.05)
                        
                    if rssi is not None:
                         print(f"RSSI is -{rssi} dBm")
                         resp_data = bytes([rssi])
                    else:
                         print("Failed to get RSSI from XBee.")
                         status_code = 0x01 # FAIL
                         
                elif assigned_task == BaseActions.SET_SCHEDULE:
                    # Payload: Action(1) Token(1) Len(1) Timestamp(4)
                    if len(pkt.payload) >= 7:
                        wake_ts = struct.unpack('>I', bytes(pkt.payload[3:7]))[0]
                        print(f"Executing SET_SCHEDULE: TDM Assigned next Base wake window at {wake_ts}")
                        try:
                            # Persist this to the volatile RAM disk. 
                            # The OS shutdown/fleet_manager routine must grab this before power cut.
                            with open('/media/cam_grabs/next_wake.txt', 'w') as f:
                                f.write(str(wake_ts))
                            status_code = 0x00 # SUCCESS
                        except Exception as e:
                            print(f"Failed to persist TDM schedule: {e}")
                            status_code = 0x01 # FAIL
                    else:
                        status_code = 0x01 # FAIL (Missing Data)
                
                elif assigned_task == BaseActions.NAP:
                    print("Executing NAP: Aborting State Machine and Yielding to Fleet Manager.")
                    return False
                    
                elif assigned_task == BaseActions.DELETE_FILE:
                    # Payload: b"IMG0004.JPG|4512345"
                    try:
                        payload_str = pkt.payload[2:].decode('utf-8')
                        if '|' in payload_str:
                            filename, size_str = payload_str.split('|', 1)
                            expected_size = int(size_str)
                            
                            from api_client import ProxyClient
                            proxy = ProxyClient()
                            if proxy.delete_camera_file(filename, expected_size):
                                status_code = 0x00
                            else:
                                status_code = 0x01
                        else:
                            print(f"Malformed DELETE_FILE payload: {payload_str}")
                            status_code = 0x01
                    except Exception as e:
                        print(f"Delete Execution Error: {e}")
                        status_code = 0x01
                        
                elif 0x80 <= assigned_task <= 0x8F:
                    print(f"Executing CAMERA PROXY ACTION: 0x{assigned_task:02X}")
                    try:
                        from api_client import ProxyClient
                        proxy = ProxyClient()
                        # Token is at index 1. Any parameters start at index 2.
                        param_val = pkt.payload[2] if len(pkt.payload) > 2 else None
                        if proxy.execute_proxy_action(assigned_task, param_val):
                            status_code = 0x00 # SUCCESS
                        else:
                            status_code = 0x01 # FAIL
                    except Exception as e:
                        print(f"Proxy Client Error: {e}")
                        status_code = 0x01
                else:
                    # Mock execution for other tasks
                    time.sleep(0.5)
                    print(f"Mocked Execution for Task 0x{assigned_task:02X}")
                
                print(f"Sending TASK_RESPONSE (Status {status_code})...")
                resp_payload = struct.pack('BBBB', assigned_task, assigned_token, status_code, len(resp_data)) + resp_data
                tr_pkt = Packet(BASE_NODE_ID, MY_NODE_ID, PacketType.TASK_RESPONSE, resp_payload)
                self.device.xfer2(self.device.build_transmit_request(self.base_addr_64, self.base_addr_16, tr_pkt.to_bytes()))
                
        return True

    def stop(self):
        self.device.close()

    def send_file_blast(self, file_path):
        """
        Sends file in 'Blast Mode' over SPI
        """
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        file_id = 1 
        
        print(f"Preparing to BLAST {file_name} ({file_size} bytes)...")
        
        # CRC Check (Full File)
        with open(file_path, 'rb') as f:
            content = f.read()
        file_crc = calculate_crc16(content)
        
        # Calculate Packets
        num_packets = (file_size + BLAST_PAYLOAD_SIZE - 1) // BLAST_PAYLOAD_SIZE
        
        print("Starting Blast Handshake (Iterative Power Scaling)...")
        for pl in range(5):
            print(f"Setting TX Power Level to PL={pl}...")
            self.device.xfer2(self.device.build_at_command("PL", bytes([pl]), frame_id=10))
            time.sleep(0.02)
            self.device.read_available()
            
            payload = bytes([file_id, 
                             (file_size >> 16) & 0xFF, (file_size >> 8) & 0xFF, file_size & 0xFF,
                             (num_packets >> 8) & 0xFF, num_packets & 0xFF,
                             (file_crc >> 8) & 0xFF, file_crc & 0xFF,
                             0x01, # Flag 0x01 = Blast Mode
                             pl])  # Current PL
                             
            for attempt in range(2):
                req_type = PacketType.REQ_RELAY_XFER if self.is_relay_mode else PacketType.REQ_XFER
                print(f"Sending {req_type.name} (Blast, PL={pl}) - Attempt {attempt+1}...")
                self.broadcast_packet(req_type, payload)
                
                self.base_addr_64, self.base_addr_16, target_pl, data_mac = self.wait_for_approve(file_id, timeout=3)
                if self.base_addr_64:
                    print(f"Approved! Target MAC (Control): {self.base_addr_64.hex()}")
                    print(f"Base instructs Mule to use Target PL={target_pl} for Data Link.")
                    print(f"Base explicitly routes Data Link to MAC: {data_mac.hex()}")
                    
                    self.device.xfer2(self.device.build_at_command("DB", frame_id=31))
                    time.sleep(0.02)
                    mule_rssi = "Unknown"
                    for f_db in self.device.read_available():
                        p_db = self.device.parse_frame(f_db)
                        if p_db and p_db.get('type') == 'at_response' and p_db.get('command') == 'DB' and len(p_db['data']) > 0:
                            mule_rssi = f"-{p_db['data'][0]} dBm"
                    print(f"Base Station RSSI as seen by Mule: {mule_rssi}")
                    
                    if self.base_addr_16 is None: self.base_addr_16 = b'\xFF\xFE'
                    
                    # Store explicitly routed Base MAC for Blast loop
                    self.base_data_addr_64 = data_mac
                    
                    # Set the commanded Final PL
                    if target_pl != pl:
                        self.device.xfer2(self.device.build_at_command("PL", bytes([target_pl]), frame_id=11))
                        time.sleep(0.02)
                        self.device.read_available()
                    break
            if self.base_addr_64:
                break
        
        if not self.base_addr_64:
            print("Iterative Handshake Failed across all PLs.")
            print("Triggering Phase 10: 200K Max Power Fallback Mode...")
            # Removed TR=0 (10 Kbps) shift as Base Station only has one radio (ttyUSB0)
            self.device.xfer2(self.device.build_at_command("PL", b'\x04', frame_id=13))
            time.sleep(0.05)
            self.device.read_available()
            
            # Update payload to PL=4
            payload = bytes([file_id, 
                             (file_size >> 16) & 0xFF, (file_size >> 8) & 0xFF, file_size & 0xFF,
                             (num_packets >> 8) & 0xFF, num_packets & 0xFF,
                             (file_crc >> 8) & 0xFF, file_crc & 0xFF,
                             0x01, # Flag 0x01 = Blast Mode
                             0x04]) # PL=4
            
            for attempt in range(2):
                req_type = PacketType.REQ_RELAY_XFER if self.is_relay_mode else PacketType.REQ_XFER
                print(f"Sending {req_type.name} (200K Max Failsafe, PL=4) - Attempt {attempt+1}...")
                self.broadcast_packet(req_type, payload)
                
                self.base_addr_64, self.base_addr_16, target_pl, data_mac = self.wait_for_approve(file_id, timeout=5)
                if self.base_addr_64:
                    print(f"200K Max Fallback Approved! Target MAC (Control): {self.base_addr_64.hex()}")
                    print(f"Base explicitly routes Data Link to MAC: {data_mac.hex()}")
                    
                    self.device.xfer2(self.device.build_at_command("DB", frame_id=31))
                    time.sleep(0.02)
                    mule_rssi = "Unknown"
                    for f_db in self.device.read_available():
                        p_db = self.device.parse_frame(f_db)
                        if p_db and p_db.get('type') == 'at_response' and p_db.get('command') == 'DB' and len(p_db['data']) > 0:
                            mule_rssi = f"-{p_db['data'][0]} dBm"
                    print(f"Base Station RSSI as seen by Mule: {mule_rssi}")
                    
                    if self.base_addr_16 is None: self.base_addr_16 = b'\xFF\xFE'
                    self.base_data_addr_64 = data_mac
                    break
        
        if not self.base_addr_64:
            print("200K Max Failsafe Handshake Failed. Aborting file transfer.")
            return False
            
        print("Restoring Volatile Parameters for Blast...")
        self.device.xfer2(self.device.build_at_command("TR", b'\x01', frame_id=14))
        # Zero-Power Handshake Boundary Gap: Safely grant the Pi 4 base station 
        # Python daemon 500ms to exit its blocking AT configuration thread and 
        # restart the OS-level UART packet parser before drowning its buffer.
        time.sleep(0.50)
        self.device.read_available()
            
        # 2. Blast Loop
        print("Blasting Data (Dynamic Window Mode)...")
        start_time = time.time()
        
        # State Arrays
        window_geometries = [128, 64, 32, 16]
        header_flags = [0xA0, 0xA1, 0xA2, 0xA3]
        current_gear = 0 # Start at 128
        
        WINDOW_SIZE = window_geometries[current_gear]
        CURRENT_HEADER = header_flags[current_gear]
        
        # Pre-read chunks for fast rewinding
        chunks = []
        with open(file_path, 'rb') as f:
            while True:
                c = f.read(BLAST_PAYLOAD_SIZE)
                if not c: break
                chunks.append(c)
                
        num_packets = len(chunks)
        window_start = 1
        total_p = 0
        consecutive_success = 0
        consecutive_failures = 0
        MAX_RETRIES = 5
        
        # GROK NOTE: This is the Asynchronous Dynamic Sliding Window architecture.
        # It aggressively pushes packets and mathematically reacts to the spectrum.
        while window_start <= num_packets:
            end_seq = min(window_start + WINDOW_SIZE - 1, num_packets)
            
            # Send current window
            for seq in range(window_start, end_seq + 1):
                chunk = chunks[seq - 1]
                
                # Prefix the payload with the dynamic gear header
                raw_packet = bytes([CURRENT_HEADER]) + struct.pack('>H', seq) + bytes(chunk)
                try:
                    # Force 0xFF 0xFE for 16-bit address to avoid 'Route Not Found' (0x25) errors
                    # Exploit Dual-Radio routing by mapping directly to self.base_data_addr_64
                    self.device.blast_data(self.base_data_addr_64, b'\xFF\xFE', raw_packet, frame_id=self.frame_id_counter)     
                    self.frame_id_counter = (self.frame_id_counter % 255) + 1
                except Exception as e:
                    if not self.summary_mode:
                        print(f"TX Error: {e}")
                total_p += 1
                
                # Dynamic Piecewise Pacing Curve
                # emp_pacing = (len(chunk) * 8 / 200000) + 0.006 (airtime + fixed margin)
                curve_base = 0.013
                emp_pacing = curve_base + ((len(chunk) - 200) * 0.0002) if len(chunk) > 200 else curve_base
                time.sleep(emp_pacing)
                
            # Wait for SSACK Boundary Synchronization or REQUEST_PKT Hole Map
            if True:
                status, missing_seqs = self.wait_for_ssack_or_request(file_id, num_packets, timeout=1.5)
                
                if status == 'ssack':
                    # SSACK Received cleanly.
                    window_start += WINDOW_SIZE
                    consecutive_success += 1
                    consecutive_failures = 0
                    
                    # Optional Up-Shift: If it survives 3 bursts, shift up a gear!
                    if consecutive_success >= 3 and current_gear > 0:
                        current_gear -= 1
                        WINDOW_SIZE = window_geometries[current_gear]
                        CURRENT_HEADER = header_flags[current_gear]
                        consecutive_success = 0
                        print(f"Signal solid. Up-Shifting Window to {WINDOW_SIZE}...")
                        
                    # Dynamic Pacing Micro-Adjustment
                    if consecutive_success >= 3:
                        pass # self.pacing_offset = max(0.010, self.pacing_offset - 0.001)
                        
                elif status == 'request':
                    # SELECTIVE REPEAT LITE: Base is requesting specific dropped sequences!
                    print(f"Base requested targeted re-blast of {len(missing_seqs)} holes! Patching...")
                    consecutive_success = 0
                    
                    # Exploit Base Station Native Modulo Math by appending the window boundary!
                    if end_seq not in missing_seqs:
                        missing_seqs.append(end_seq)
                        
                    patch_attempts = 0
                    max_patch_attempts = 3
                    patch_success = False
                    
                    while patch_attempts < max_patch_attempts:
                        for m_seq in missing_seqs:
                            if m_seq <= num_packets: # Safety bound
                                chunk = chunks[m_seq - 1]
                                raw_packet = bytes([CURRENT_HEADER]) + struct.pack('>H', m_seq) + bytes(chunk)
                                try:
                                    # Exploit Dual-Radio routing mapping
                                    self.device.blast_data(self.base_data_addr_64, b'\xFF\xFE', raw_packet, frame_id=self.frame_id_counter)     
                                    self.frame_id_counter = (self.frame_id_counter % 255) + 1
                                except Exception as e:
                                    if not self.summary_mode:
                                        print(f"Patch-TX Error: {e}")
                                total_p += 1
                                # Dynamic Piecewise Pacing Curve
                                curve_base = 0.013
                                emp_pacing = curve_base + ((len(chunk) - 200) * 0.0002) if len(chunk) > 200 else curve_base
                                time.sleep(emp_pacing)
                        
                        patch_attempts += 1
                        if not self.summary_mode:
                            print(f"Patch sequence sent. Waiting for localized SSACK sync...")
                        patch_status, patch_missing = self.wait_for_ssack_or_request(file_id, num_packets, timeout=1.5)
                        
                        if patch_status == 'ssack':
                            window_start += WINDOW_SIZE
                            consecutive_failures = 0
                            patch_success = True
                            if not self.summary_mode:
                                print("Localized Patch Successful! Resuming main array...")
                            break
                        elif patch_status == 'request':
                            missing_seqs = patch_missing
                            if end_seq not in missing_seqs:
                                missing_seqs.append(end_seq)
                            if not self.summary_mode:
                                print(f"Patch still had holes? Trying patch attempt {patch_attempts+1}/{max_patch_attempts}...")
                        else:
                            if not self.summary_mode:
                                print("Timeout waiting for Patch SSACK. Retrying patches...")
                                
                    if not patch_success:
                        if not self.summary_mode:
                            print("Failed to patch window after max attempts. Giving up and rewriting whole window.")
                        consecutive_failures += 1
                        
                        # Phase 17: Dynamic Mid-Stream Burst Scaling (Patch Timeout Trigger)
                        # If targeted SSACK patches repeatedly fail, punch the absolute power up!
                        if consecutive_failures == 3 and pl < 4:
                            pl += 1
                            print(f"\n[!] Mid-Stream Interference Detected: Bursting Power Level upwards to PL={pl}...\n")
                            self.device.xfer2(self.device.build_at_command("PL", bytes([pl]), frame_id=12))
                            time.sleep(0.02)
                            self.device.read_available()
                        
                else:
                    # Generic Timeout (Total RF wipeout) or TX Fail
                    consecutive_success = 0
                    consecutive_failures += 1
                    # self.pacing_offset = min(0.024, self.pacing_offset + 0.002)
                    
                    # Phase 17: Dynamic Mid-Stream Burst Scaling (Total Timeout Trigger)
                    if consecutive_failures == 3 and pl < 4:
                        pl += 1
                        print(f"\n[!] Mid-Stream Silence Detected: Bursting Power Level upwards to PL={pl}...\n")
                        self.device.xfer2(self.device.build_at_command("PL", bytes([pl]), frame_id=13))
                        time.sleep(0.02)
                        self.device.read_available()
                    
                    if consecutive_failures > MAX_RETRIES:
                        print(f"FATAL: Window {window_start}-{end_seq} failed {MAX_RETRIES} times! Adaptive Fallback to 10K...")
                        
                        # Command Base to max power and we'll both drop to 10K
                        pa_payload = bytes([BaseActions.POWER_ADJUST, 0x04]) # Command Base to PL=4
                        pa_pkt = Packet(BASE_NODE_ID, MY_NODE_ID, PacketType.TASK_ASSIGN, pa_payload)
                        req = self.device.build_transmit_request(self.base_data_addr_64 if hasattr(self, 'base_data_addr_64') else self.base_addr_64, b'\xFF\xFE', pa_pkt.to_bytes(), frame_id=self.frame_id_counter)
                        self.device.xfer2(req)
                        time.sleep(0.5)
                        
                        # Revert local hardware
                        self.device.xfer2(self.device.build_at_command("PL", b'\x04', frame_id=20))
                        time.sleep(0.05)
                        self.device.xfer2(self.device.build_at_command("BR", b'\x00', frame_id=21)) # Drop to 10K
                        time.sleep(0.05)
                        
                        return False
                    if not self.summary_mode:
                        print(f"Window {window_start}-{end_seq} Timeout or TX Fail! Interference Hit.")
                    # Flush the deadlocked API buffer
                    self.device.read_available()
                    # Downshift the gear if possible
                    if current_gear < len(window_geometries) - 1:
                        current_gear += 1
                        WINDOW_SIZE = window_geometries[current_gear]
                        CURRENT_HEADER = header_flags[current_gear]
                        if not self.summary_mode:
                            print(f"Down-Shifting Window directly to {WINDOW_SIZE} packets!")
                    else:
                        if not self.summary_mode:
                            print("Already at minimum Window Size! Brute-forcing...")
                    # Loop restarts and re-blasts from the exact same window_start
            else:
                window_start += WINDOW_SIZE
        
        blast_time = time.time() - start_time
        if not self.summary_mode:
            print(f"Blast Finished. Sent {total_p} physical frames in {blast_time:.2f}s.")
        
        # 3. End Blast / Verify
        # Ensure the 200 Kbps SPI buffer is fully flushed of payload chunks before sending the critical teardown packet.
        time.sleep(0.02)
        
        if not self.summary_mode:
            print("Sending END_BLAST...")
        end_payload = bytes([file_id, (file_crc >> 8) & 0xFF, file_crc & 0xFF])
        end_pkt = Packet(BASE_NODE_ID, MY_NODE_ID, PacketType.END_BLAST, end_payload)
        
        req = self.device.build_transmit_request(self.base_addr_64, self.base_addr_16, end_pkt.to_bytes(), frame_id=0)
        self.device.xfer2(req)

        if not self.summary_mode:
            print("Waiting for Confirmation...")
            
        if self.wait_for_conf(file_id, timeout=20):
             total_time = time.time() - start_time
             rate_kbps = (file_size / 1024) / total_time if total_time > 0 else 0
             if not self.summary_mode:
                 print(f"Transfer SUCCESS! Final Steady-State Rate: {rate_kbps:.2f} KB/s")
             return True
        else:
             if not self.summary_mode:
                 print("Transfer FAILED (No Confirmation or NAK).")
             return False

    def broadcast_packet(self, msg_type, payload):
        pkt = Packet(BASE_NODE_ID, MY_NODE_ID, msg_type, payload)
        data = pkt.to_bytes()
        req = self.device.build_transmit_request(BROADCAST_64, BROADCAST_16, data, frame_id=0x01)
        self.device.xfer2(req)

    def wait_for_ssack_or_request(self, file_id, num_packets, timeout=1.5):
        """
        Multipexed listener. Waits for a standard SSACK (success),
        a TASK_ASSIGN(REQUEST_PKT) carrying a bitmap of missing sequences,
        or failing TX statuses.
        """
        start = time.time()
        while time.time() - start < timeout:
            frames = self.device.read_available()
            for frame in frames:
                parsed = self.device.parse_frame(frame)
                if parsed and parsed.get('type') == 'rx':
                    pkt = Packet.from_bytes(parsed['data'])
                    if pkt:
                        # Standard SSACK
                        if pkt.msg_type == PacketType.SSACK and pkt.payload[0] == file_id:
                            return 'ssack', []
                            
                        # TASK_ASSIGN wrapping a REQUEST_PKT
                        elif pkt.msg_type == PacketType.TASK_ASSIGN and len(pkt.payload) >= 4:
                            # Payload: [Action(1)] [FileID(1)] [WinStart_H(1)] [WinStart_L(1)] [Bitmap(N)]
                            if pkt.payload[0] == 0x08 and pkt.payload[1] == file_id: # 0x08 = BaseActions.REQUEST_PKT
                                win_start = (pkt.payload[2] << 8) | pkt.payload[3]
                                bitmap = pkt.payload[4:]
                                
                                missing_seqs = []
                                for byte_idx, byte in enumerate(bitmap):
                                    for bit_pos in range(8):
                                        if byte & (1 << bit_pos):
                                            missing_seq = win_start + (byte_idx * 8 + bit_pos)
                                            if missing_seq <= num_packets:
                                                missing_seqs.append(missing_seq)
                                            if len(missing_seqs) >= 30:
                                                if not self.summary_mode:
                                                    print("Bitmap Overflow Guard Triggered: Truncating patches to 30.")
                                                return 'request', missing_seqs
                                                
                                return 'request', missing_seqs
                                
                elif parsed and parsed.get('type') == 'tx_status':
                    if parsed.get('status') != 0:
                        if not self.summary_mode:
                            print(f"TX Failure detected (Status: 0x{parsed.get('status'):02X}). Short-circuiting timeout.")
                        return 'tx_fail', []
                
            # Yield to CPU
            time.sleep(0.002)
        return 'timeout', []

    def wait_for_approve(self, file_id, timeout=2.0) -> tuple[bytes, bytes, int, bytes]:
        """Waits for an APPROVE packet from the base station returning Target PL and 64-bit Payload MAC Address."""
        start = time.time()
        while time.time() - start < timeout:
            frames = self.device.read_available()
            for f in frames:
                parsed = self.device.parse_frame(f)
                if parsed and parsed.get('type') == 'rx':
                    pkt = Packet.from_bytes(parsed['data'])
                    if pkt and pkt.msg_type == PacketType.APPROVE:
                        if len(pkt.payload) >= 10 and pkt.payload[0] == file_id:
                            target_pl = pkt.payload[1]
                            data_mac = pkt.payload[2:10]
                            return parsed['src_64'], parsed.get('src_16', b'\xFF\xFE'), target_pl, data_mac
            time.sleep(0.02)
        return None, None, 0, None

    def wait_for_conf(self, file_id, timeout=10):
        start = time.time()
        while time.time() - start < timeout:
            frames = self.device.read_available()
            if frames:
                for frame in frames:
                    parsed = self.device.parse_frame(frame)
                    if parsed and parsed.get('type') == 'rx':
                        pkt = Packet.from_bytes(parsed['data'])
                        if pkt:
                            if pkt.msg_type == PacketType.CONF_XFER:
                                 if len(pkt.payload) > 0 and pkt.payload[0] == file_id:
                                    return True
                            elif pkt.msg_type == PacketType.NAK:
                                 print("Received NAK!")
                                 return False
            else:
                time.sleep(0.02)
        return False

if __name__ == "__main__":
    uploader = MuleUploader()
    try:
        uploader.start()
        target_dir = "/media/cam_grabs/"
        
        # Temporary logic for testing deployment directly
        # Ensure fallback test files if nothing in mule_cam_grabs
        import glob
        import sys
        import random
        if len(sys.argv) > 1:
            files = [sys.argv[1]]
        else:
            all_files = glob.glob(os.path.join(target_dir, "*.avif")) + glob.glob(os.path.join(target_dir, "*.AVIF"))
            if len(all_files) >= 10:
                files = random.sample(all_files, 10)
            elif all_files:
                files = [random.choice(all_files) for _ in range(10)]
            else:
                files = []
        
        if not files:
            print(f"No AVIF files found or provided.")
        else:
            print(f"Found {len(all_files)} files. Randomly selected 10 files for the stress test.")
        
        for f in files:
            if uploader.send_file_blast(f):
                print(f"SUCCESS: {f}")
                # Zero-power hardware breathing room: Allow Base Station RF transceivers 
                # 1500ms to clear ACKs and bypass Clear Channel Assessment (CCA) saturation 
                # before the next REQ_XFER handshake.
                time.sleep(1.5)
            else:
                print(f"FAILED: {f}")       
    finally:
        uploader.stop()
