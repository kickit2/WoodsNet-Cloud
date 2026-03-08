import logging
import queue
import threading
import time
import struct
from digi.xbee.devices import XBeeDevice
from digi.xbee.models.mode import APIOutputMode
from protocol import Packet, PacketType, BaseActions, parse_header, build_header
from file_handler import FileHandler

# Config
PORT = "/dev/ttyUSB0"
BAUD_RATE = 230400
# logging.basicConfig(level=logging.WARNING) # Can't change here easily if main sets it.
# We will comment out the specific info logs.

class SessionManager:
    # --- PHASE 10: DUAL-RADIO SYNCHRONIZATION CLUSTER STATE ---
    _shared_file_handler = FileHandler()
    _shared_lock_src_id = None
    _shared_blast_mode = False
    _shared_fleet_registry = {}
    _handshake_lock = threading.Lock() # META AI FIX: Prevent simultaneous dual-mule REQ_XFER race conditions
    
    def __init__(self, device, is_data_lane=False):
        self.device = device
        self.rx_queue = queue.Queue()
        self.running = False
        self.is_data_lane = is_data_lane
        self.worker_thread = None
        self.summary_mode = True
        self.task_queue = {} # dict[src_id, queue.Queue]
        
    @property
    def file_handler(self): return SessionManager._shared_file_handler
    @property
    def lock_src_id(self): return SessionManager._shared_lock_src_id
    @lock_src_id.setter
    def lock_src_id(self, val): SessionManager._shared_lock_src_id = val
    @property
    def blast_mode(self): return SessionManager._shared_blast_mode
    @blast_mode.setter
    def blast_mode(self, val): SessionManager._shared_blast_mode = val
    @property
    def fleet_registry(self): return SessionManager._shared_fleet_registry
    @fleet_registry.setter
    def fleet_registry(self, val): SessionManager._shared_fleet_registry = val

    def start(self):
        try:
            logging.info(f"Opening XBee on {PORT}...")
            self.device.open()
            # SAFETY: Set Power Level to 0 (Low) for default proximity resting state
            self.device.set_parameter("PL", bytearray([0]))
            logging.info("XBee Power Level set to 0 (Low)")
            
            # PERFORMANCE: Set RF Data Rate (TR) to 1 (200 Kbps)
            try:
                self.device.set_parameter("TR", bytearray([0, 1])) # TR is 2 bytes? or 1? Diagnostic showed 00 00.
                # Diagnostic output `TR: bytearray(b'\x00\x00')` suggests 2 bytes. 
                # Let's try 4 bytes/bitmask? Or just try writing 1.
                # If it's a bitmask, 1 might be fine.
                # Wait, common usage is 1 byte for mode.
                # Let's try to set it to 1.
                self.device.set_parameter("TR", bytearray([1])) 
                logging.info("XBee RF Data Rate (TR) set to 1 (200 Kbps)")
            except Exception as e:
                logging.warning(f"Could not set TR=1: {e}")
                
            try:
                np_val = self.device.get_parameter("NP")
                if np_val:
                    logging.info(f"XBee Network Payload (NP) Maximum: {int.from_bytes(np_val, 'big')} bytes")
            except Exception as e:
                logging.warning(f"Could not read NP parameter: {e}")
            
            self.device.add_data_received_callback(self.data_callback)
            self.running = True
            self.worker_thread = threading.Thread(target=self.process_loop)
            self.worker_thread.daemon = True
            self.worker_thread.start()
            
            self.gc_thread = threading.Thread(target=self.gc_loop)
            self.gc_thread.daemon = True
            self.gc_thread.start()

            logging.info(f"Faux Base listening on {PORT}...")
            
        except Exception as e:
            logging.error(f"Failed to open XBee: {e}")
            self.running = False

    def stop(self):
        self.running = False
        if self.device.is_open():
            self.device.close()

    def data_callback(self, xbee_message):
        self.rx_queue.put(xbee_message)

    def gc_loop(self):
        """GROK Review Fix: Background thread to prune stale sessions if Mule drops offline."""
        while self.running:
            time.sleep(30)
            now = time.time()
            stale_threshold = 60 # Seconds
            
            with self.file_handler.lock:
                to_remove = []
                for src_id, tx in self.file_handler.active_transactions.items():
                    if now - getattr(tx, 'last_activity_time', now) > stale_threshold:
                        logging.warning(f"Garbage Collecting Stale Session {src_id}!")
                        to_remove.append(src_id)
                
                for src_id in to_remove:
                    self.file_handler.end_transaction(src_id)
                    if self.lock_src_id == src_id:
                        self.lock_src_id = None
                        self.blast_mode = False

    def send_response(self, remote, original_pkt, msg_type, payload=b''):
        # Construct response
        # Dest_ID = original_pkt.src (Node ID)
        # Src_ID = 0xF (Base)
        
        base_id = 0xF
        resp = Packet(original_pkt.src, base_id, msg_type, payload)
        data = resp.to_bytes()
        
        try:
            # SAFETY: Small delay REMOVED for high speed
            # time.sleep(0.5) 
            addr = remote.get_64bit_addr()
            # logging.info(f"Attempting valid Unicast to {addr} (PL0)...")
            self.device.send_data(remote, data)
            logging.info(f"Sent {PacketType(msg_type).name}")
        except Exception as e:
            logging.error(f"Failed to send response: {e}")

    def process_loop(self):
        while self.running:
            try:
                msg = self.rx_queue.get(timeout=1)
            except queue.Empty:
                continue

            data = msg.data
            remote = msg.remote_device
            
            pkt = Packet.from_bytes(msg.data)
            
            if pkt is None:
                # Ignore empty/too short (Noise?)
                # But log if it has size
                if len(msg.data) > 0:
                     logging.warning(f"Invalid Packet Structure (Len {len(msg.data)}): {msg.data.hex()}")
                continue
                
            if not pkt.valid:
                logging.warning(f"CRC Error in Header from {remote.get_64bit_addr()}. Raw: {msg.data.hex()}")
                # Optional: Send NAK
                continue

            self.handle_packet(pkt, remote)

    def handle_packet(self, pkt: Packet, remote):
        import time
        import struct
        import queue
        # Dispatch based on Message Type
        logging.info(f"RX PKT: msg_type={pkt.msg_type.name if hasattr(pkt.msg_type, 'name') else pkt.msg_type}, src={pkt.src}, len={len(pkt.payload)}")
        # --- Type 6: Heartbeat ---
        if pkt.msg_type == PacketType.HEARTBEAT:
            if len(pkt.payload) >= 2:
                v = pkt.payload[0] / 50.0
                status = pkt.payload[1]
                logging.info(f"Heartbeat from Node {pkt.src}: {v:.2f}V, Status 0x{status:02X}")
                
            # Clear stale lock if node rebooted/screamed
            if self.lock_src_id == pkt.src:
                logging.info(f"Node {pkt.src} rebooted. Clearing active lock.")
                self.file_handler.end_transaction(pkt.src)
                self.lock_src_id = None
                self.blast_mode = False
                
            # --- PHASE 13: DYNAMIC FLEET REGISTRY & TDM ---
            # Prune dead mules (not seen in 48 hours)
            current_time = int(time.time())
            self.fleet_registry = {n: ts for n, ts in self.fleet_registry.items() if current_time - ts < 172800}
            
            # Update current Mule/Relay
            self.fleet_registry[pkt.src] = current_time
            
            # Phase 10: Relay Store & Forward Topology
            RELAY_MAP = {4: 1, 5: 2, 6: 3} # Relay 4 manages Mule 1, etc.
            
            # Extract standard Mules for base time division
            mule_registry = {n: ts for n, ts in self.fleet_registry.items() if n not in RELAY_MAP}
            active_mule_count = max(1, len(mule_registry))
            
            # Sort active nodes mathematically to assign sequential TDM slots
            sorted_mules = sorted(list(mule_registry.keys()))
            
            # Divide 24 hours (86400 seconds) by active mules
            window_size_sec = 86400 // active_mule_count
            
            # Calculate next absolute wake constraint
            # Align to midnight (UTC or Local epoch base) 
            day_base = current_time - (current_time % 86400) 
            
            if pkt.src in RELAY_MAP:
                child_id = RELAY_MAP[pkt.src]
                if child_id in sorted_mules:
                    child_idx = sorted_mules.index(child_id)
                    base_wake = day_base + (window_size_sec * child_idx)
                    next_wake = base_wake + 3600 # 1 hour offset for Store & Forward
                else:
                    # Backup if child offline
                    next_wake = day_base + 3600
            else:
                if pkt.src in sorted_mules:
                    my_tdm_index = sorted_mules.index(pkt.src)
                else:
                    my_tdm_index = 0
                next_wake = day_base + (window_size_sec * my_tdm_index)
            
            # If the calculated window already passed today, push it to tomorrow
            if next_wake <= current_time:
                next_wake += 86400
                
            node_role = "RELAY" if pkt.src in RELAY_MAP else "MULE"
            logging.info(f"[TDM] Fleet Size: {active_mule_count} | {node_role} {pkt.src} | Next Wake: {next_wake}")
                
            # Seed testing tasks for Phase 7 + Phase 13 Target
            if pkt.src not in self.task_queue:
                self.task_queue[pkt.src] = queue.Queue()
                # 1. SYNC_TIME (Data: 4-byte UNIX epoch)
                ts = struct.pack('>I', current_time)
                self.task_queue[pkt.src].put((BaseActions.SYNC_TIME, 0x11, ts))
                # 2. SET_SCHEDULE (Data: 4-byte UNIX epoch for Next Wake)
                wake_bytes = struct.pack('>I', next_wake)
                self.task_queue[pkt.src].put((BaseActions.SET_SCHEDULE, 0x15, wake_bytes))
                # 3. GET_NODE_RSSI (No Data)
                self.task_queue[pkt.src].put((BaseActions.GET_NODE_RSSI, 0x22, b''))
                
            self.send_response(remote, pkt, PacketType.SSACK)

        # --- Type 7: Task Query ---
        elif pkt.msg_type == PacketType.TASK_QUERY:
            logging.info(f"Task Query from Node {pkt.src}")
            
            node_q = self.task_queue.get(pkt.src)
            if node_q and not node_q.empty():
                task_data = node_q.get()
                action = task_data[0]
                token = task_data[1]
                t_data = task_data[2] if len(task_data) > 2 else b''
                
                logging.info(f"Assigning Task {BaseActions(action).name} to Node {pkt.src}")
                # Type 8 Structure: [Action(1)][Token(1)][Len(1)][Data]
                payload = bytes([action, token, len(t_data)]) + t_data
            else:
                logging.info(f"No Tasks for Node {pkt.src}. Yielding.")
                # Action 0x09 (No Task)
                payload = bytes([BaseActions.NO_TASK, 0, 0])
                
            self.send_response(remote, pkt, PacketType.TASK_ASSIGN, payload)
            
        # --- Type 9: Task Response ---
        elif pkt.msg_type == PacketType.TASK_RESPONSE:
            if len(pkt.payload) >= 3:
                action = pkt.payload[0]
                token = pkt.payload[1]
                status = pkt.payload[2]
                try:
                    action_name = BaseActions(action).name
                except ValueError:
                    action_name = f"UNKNOWN (0x{action:02X})"
                
                logging.info(f"Task Response from Node {pkt.src} for {action_name} [Token: 0x{token:02X}]: Status {status}")
                
                # Parse additional data based on Action
                if len(pkt.payload) >= 4:
                    data_len = pkt.payload[3]
                    resp_data = pkt.payload[4:4+data_len]
                    
                    if action == BaseActions.SYNC_TIME and len(resp_data) == 4:
                        echoed_ts = struct.unpack('>I', resp_data)[0]
                        logging.info(f"  -> Mule Echoed Time: {echoed_ts}")
                        
                    elif action == BaseActions.GET_NODE_RSSI and len(resp_data) >= 1:
                        # Mule sends RSSI as a positive integer byte (e.g., 0x4B = 75 = -75 dBm)
                        rssi_val = -int(resp_data[0])
                        logging.info(f"  -> Mule reported active RSSI: {rssi_val} dBm")

        # --- Type 8: Task Assign (Reverse commanding from Mule) ---
        elif pkt.msg_type == PacketType.TASK_ASSIGN:
            if len(pkt.payload) >= 2:
                action = pkt.payload[0]
                if action == BaseActions.POWER_ADJUST:
                    target_pl = pkt.payload[1]
                    logging.warning(f"Mule {pkt.src} commanded Base to POWER_ADJUST PL={target_pl} (Interference Fallback)")
                    try:
                        self.device.set_parameter("PL", bytearray([target_pl]))
                    except Exception as e:
                        logging.error(f"Failed to reverse-adjust PL: {e}")

        # --- Type 4: Req Xfer (Standard or Blast) ---
        # --- Type 4 / Type 13: Req Xfer (Standard / Relay or Blast) ---
        elif pkt.msg_type in (PacketType.REQ_XFER, PacketType.REQ_RELAY_XFER):
            # Payload: [ID(1)][Size(3)][Pkts(2)][CRC(2)] + Optional [Flags(1)]
            if len(pkt.payload) >= 8:
                file_id = pkt.payload[0]
                size = (pkt.payload[1] << 16) | (pkt.payload[2] << 8) | pkt.payload[3]
                num_packets = (pkt.payload[4] << 8) | pkt.payload[5]
                file_crc = (pkt.payload[6] << 8) | pkt.payload[7]
                
                mule_pl = 4 # Default if legacy length
                is_blast = False
                
                if len(pkt.payload) >= 10:
                    is_blast = (pkt.payload[8] & 0x01) != 0
                    mule_pl = pkt.payload[9]
                elif len(pkt.payload) >= 9:
                    is_blast = (pkt.payload[8] & 0x01) != 0
                
                type_str = "BLAST" if is_blast else "Standard"
                is_relay = (pkt.msg_type == PacketType.REQ_RELAY_XFER)
                req_type = "Relay (Store & Forward)" if is_relay else "Direct Payload"
                
                # DYNAMIC HARDWARE TELEMETRY:
                # Query the physical XBee transceiver locally for the active db index 
                # (Signal Strength) of the exactly matched incoming handshake packet!
                base_rssi = "Unknown"
                try:
                    db_bytes = self.device.get_parameter("DB")
                    if db_bytes:
                        base_rssi = f"-{int.from_bytes(db_bytes, byteorder='big')} dBm"
                except Exception as e:
                    pass
                
                logging.info(f"Req {type_str} [{req_type}] from Node {pkt.src}: File {file_id}, Size {size}B, Pkts {num_packets}, Rx PL={mule_pl}, Incoming Mule RSSI: {base_rssi}")
                
                if self.lock_src_id is not None and self.lock_src_id != pkt.src:
                    logging.warning(f"Rejecting Node {pkt.src} (Locked by {self.lock_src_id})")
                    self.send_response(remote, pkt, PacketType.BUSY, bytes([10]))
                else:
                    with SessionManager._handshake_lock:
                        if self.lock_src_id is not None and self.lock_src_id != pkt.src:
                            logging.warning(f"Rejecting Node {pkt.src} (Locked by {self.lock_src_id}) during race condition.")
                            self.send_response(remote, pkt, PacketType.BUSY, bytes([10]))
                            return
                            
                        self.lock_src_id = pkt.src
                        self.blast_mode = is_blast
                        self.file_handler.start_transaction(pkt.src, file_id, size, num_packets, file_crc)
                    
                    target_pl = mule_pl # Echo the successful PL back, trusting Mule's iterative loop
                    
                    # DYNAMIC ASYMMETRICAL RESOLUTION:
                    # Dynamically set our *own* transmitting hardware to match the Mule's successful PL array 
                    # before attempting to push the APPROVE payload across the RF distance!
                    try:
                        self.device.set_parameter("PL", bytearray([target_pl]))
                        logging.info(f"Dynamically mirroring TX Power Level to PL={target_pl} for active handshake.")
                    except Exception as e:
                        logging.error(f"Failed to dynamically adjust PL: {e}")
                    
                    # Synthesizing Dual-Radio execution for Payload Target MAC mapping
                    # When parallel thread model is active, this maps to explicit payload transceiver
                    local_mac_64 = self.device.get_64bit_addr().address 
                    # Structure: [File_ID(1)][Target_PL(1)][Data_MAC(8)]
                    approve_payload = bytes([file_id, target_pl]) + local_mac_64
                    self.send_response(remote, pkt, PacketType.APPROVE, approve_payload)

        # --- Type 15: End Blast ---
        elif pkt.msg_type == PacketType.END_BLAST:
            if self.lock_src_id is not None:
                # Payload: [FileID][CRC(2)?] Or just trust internal calc?
                # User said: "End of binary transmission - heres the full file CRC"
                # Let's assume payload is [FileID][CRC_High][CRC_Low]
                if len(pkt.payload) >= 3:
                     file_id = pkt.payload[0]
                     rx_crc = (pkt.payload[1] << 8) | pkt.payload[2]
                     
                     logging.info(f"End Blast for File {file_id}. Verifying CRC...")
                     tx = self.file_handler.get_transaction(self.lock_src_id)
                     if tx:
                         elapsed_time = time.time() - getattr(tx, 'start_time', time.time()-1)
                         kb_size = tx.file_size / 1024
                         kb_per_sec = kb_size / elapsed_time if elapsed_time > 0 else 0
                         
                         if tx.finalize():
                             logging.info(f"Base Station SUCCESS! Received {kb_size:.2f} KB in {elapsed_time:.2f}s => Speed: {kb_per_sec:.2f} KB/s")
                             self.send_response(remote, pkt, PacketType.CONF_XFER, bytes([file_id]))
                         else:
                             logging.warning(f"Blast Verification Failed! Corrupted Size/CRC. Time taken: {elapsed_time:.2f}s")
                             self.send_response(remote, pkt, PacketType.NAK, bytes([file_id])) # Specific NAK
                         
                         self.lock_src_id = None
                         self.blast_mode = False
                         self.file_handler.end_transaction(pkt.src)

        # --- Type 10: File Data & Dynamic Blast Windows ---
        elif pkt.msg_type == PacketType.FILE_DATA:
            # Special handling for Blast Mode (src=0)
            src_id = pkt.src
            if src_id == 0 and self.lock_src_id is not None:
                 src_id = self.lock_src_id
            
            if self.lock_src_id != src_id:
                 logging.warning(f"Unexpected Data from {src_id} (Locked: {self.lock_src_id})")
                 self.send_response(remote, pkt, PacketType.XFER_FAIL, bytes([0]))
                 return

            if len(pkt.payload) < 3: # ID(1) Seq(2)
                return 
                
            file_id = pkt.payload[0]
            seq = (pkt.payload[1] << 8) | pkt.payload[2]
            data_chunk = pkt.payload[3:]
            
            tx = self.file_handler.get_transaction(src_id)
            if tx:
                tx.write_chunk(seq, data_chunk)
                
                # Windowed ACK logic
                if getattr(self, 'blast_mode', False):
                    # Dynamically set the expected window size based on the specific safe bypass gear property
                    if getattr(pkt, 'bypass_window_size', None) is not None:
                        self.current_window_size = pkt.bypass_window_size
                    elif not hasattr(self, 'current_window_size'):
                        self.current_window_size = 64 # Fallback
                        
                    # GROK NOTE: Dynamic Sliding Window implementation.
                    # Determine which window this packet mathematically belongs to
                    window_start = ((seq - 1) // self.current_window_size) * self.current_window_size + 1
                    window_end = min(window_start + self.current_window_size - 1, tx.expected_packets)
                    
                    # Use our new file_handler utility to calculate holes
                    missing = tx.get_missing_sequences(tx.expected_packets, window_start, window_end)
                    
                    if not missing:
                        if not hasattr(tx, 'acked_windows'):
                            tx.acked_windows = set()
                        # If this window is fully complete and we haven't SSACK'd it yet
                        if window_start not in tx.acked_windows:
                            tx.acked_windows.add(window_start)
                            self.send_response(remote, pkt, PacketType.SSACK, bytes([file_id]))
                    else:
                        # Window still has holes.
                        # Only issue the REQUEST_PKT when the Mule naturally hits the boundary of this window.
                        is_window_boundary = (seq % self.current_window_size == 0 and seq > 0)
                        is_last_packet = tx.expected_packets == seq
                        
                        if is_window_boundary or is_last_packet:
                            logging.warning(f"BLAST HOLE DETECTED! Missing {len(missing)} packets in window {window_start}-{window_end}. Sending REQUEST_PKT Bitmap.")
                            bitmap = bytearray((self.current_window_size + 7) // 8)
                            for m in missing:
                                bit_index = m - window_start
                                byte_idx = bit_index // 8
                                bit_pos = bit_index % 8
                                bitmap[byte_idx] |= (1 << bit_pos)
                                
                            payload = bytes([BaseActions.REQUEST_PKT, file_id, (window_start >> 8) & 0xFF, window_start & 0xFF]) + bitmap
                            self.send_response(remote, pkt, PacketType.TASK_ASSIGN, payload)
                else:
                    # Standard Mode: 128-packet window size
                    if seq % 128 == 0:
                        self.send_response(remote, pkt, PacketType.SSACK, bytes([file_id]))
                
                # Check completion by packet count (Standard Mode only?)
                # In Blast Mode, we wait for END_BLAST.
                if not getattr(self, 'blast_mode', False):
                    if tx.received_packets >= tx.expected_packets:
                        logging.info(f"Transfer Complete (Pkts: {tx.received_packets}). Verifying...")
                        if tx.finalize():
                            self.send_response(remote, pkt, PacketType.CONF_XFER, bytes([file_id]))
                        else:
                            self.send_response(remote, pkt, PacketType.XFER_FAIL, bytes([file_id]))
                            
                        self.lock_src_id = None
                        self.file_handler.end_transaction(src_id)
