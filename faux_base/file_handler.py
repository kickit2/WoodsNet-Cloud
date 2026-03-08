import os
import struct
import logging
from protocol import calculate_crc16, TYPE10_DATA_SIZE

RECEIVE_DIR = "received_files"

class FileTransaction:
    def __init__(self, src_id, file_id, file_size, expected_packets, expected_crc):
        self.src_id = src_id
        self.file_id = file_id
        self.file_size = file_size
        self.expected_packets = expected_packets
        self.expected_crc = expected_crc
        self.received_packets = 0
        self.received_sequences = set()
        self.last_sequence = -1
        self.temp_filename = f"{RECEIVE_DIR}/temp_{src_id}_{file_id}.dat"
        self.final_filename = f"{RECEIVE_DIR}/node{src_id}_img{file_id}.avif"
        self.final_filename = f"{RECEIVE_DIR}/node{src_id}_img{file_id}.avif"
        import time
        self.last_activity_time = time.time()
        self.start_time = time.time()
        
        # Ensure directory exists
        os.makedirs(RECEIVE_DIR, exist_ok=True)
        
        # Open file natively in wb+ to permit inline seek/read validation during duplicated frames
        self.handle = None
        try:
            self.handle = open(self.temp_filename, "wb+")
        except Exception as e:
            logging.error(f"Failed to open temp file: {e}")
            self.handle = None

    def write_chunk(self, seq_num, data):
        if not self.handle:
            return False
            
        import time
        self.last_activity_time = time.time()
        
        if seq_num in self.received_sequences:
            # Duplicate Sequence Detected. 
            # We safely ignore the rewrite, the file structure already contains this chunk.
            return True
            
        # Check Sequence
        # If seq_num != self.last_sequence + 1:
            # logging.warning(f"Sequence gap! Expected {self.last_sequence + 1}, got {seq_num}")
            # In a real system we might request a resend (Action 0x08 Request Pkt)
            # For now, we just write it (assuming the gap is handled or we just accept corruption for this Mule MVP)
            # Spec says "Selective Repeat (Hole filling)" which implies we should handle it.
            # But "Hole filling" is an advanced feature.
            # Let's simple write for now.
        
        offset = (seq_num - 1) * TYPE10_DATA_SIZE
        self.handle.seek(offset)
        # Structural Assumption: Type 10 structure is bounded by physical 95-Byte MTU limits.
        # Spec Table Total = 100 bytes is considered a logical maximum prior to standard 95-byte fragmentation.
        pass # To be continued in write
        
        self.handle.write(data)
        
        if seq_num not in self.received_sequences:
            self.received_sequences.add(seq_num)
            self.received_packets += 1
            
        self.last_sequence = seq_num
        
    def get_missing_sequences(self, expected_total, start_seq=None, end_seq=None):
        if start_seq is None:
            start_seq = 1
        if end_seq is None:
            end_seq = expected_total
            
        # Hard cap to the absolute expected packets geometry
        end_seq = min(end_seq, self.expected_packets)
        
        missing = []
        for seq in range(start_seq, end_seq + 1):
            if seq not in self.received_sequences:
                missing.append(seq)
        return missing

    def finalize(self):
        if self.handle:
            self.handle.close()
            
        # Verify CRC
        # Read file back
        with open(self.temp_filename, "rb") as f:
            content = f.read()
            
        calc_crc = calculate_crc16(content)
        
        if calc_crc == self.expected_crc:
            if len(content) != self.file_size:
                logging.warning(f"File Size Mismatch! Expected {self.file_size} bytes, got {len(content)} bytes. CRC passed erroneously!")
                return False
                
            os.rename(self.temp_filename, self.final_filename)
            logging.info(f"File transaction successful: {self.final_filename} ({len(content)} bytes)")
            
            # --- CLOUD INTEGRATION TRIGGER ---
            try:
                from cloud_uploader import CloudUploader
                # In a real deployment, this URL would be injected via environment variables or a config file
                import os
                api_url = os.environ.get('AWS_API_URL', 'https://REPLACE_WITH_API_ID.execute-api.us-east-1.amazonaws.com/get-upload-url')
                uploader = CloudUploader(api_url)
                
                # Extract filename from path (e.g. node1_img4.avif)
                final_name = os.path.basename(self.final_filename)
                mule_id = f"MULE{self.src_id:02X}"
                
                uploader.upload_file_async(self.final_filename, final_name, mule_id)
            except Exception as e:
                logging.error(f"Failed to trigger cloud upload: {e}")
            # ---------------------------------
                
            if os.path.exists(self.temp_filename):
                os.remove(self.temp_filename)
            return True
        else:
            logging.error(f"CRC Mismatch! Expected {self.expected_crc:04X}, got {calc_crc:04X}")
            return False

    def cleanup(self):
        if self.handle:
            self.handle.close()
        if os.path.exists(self.temp_filename):
            os.remove(self.temp_filename)

class FileHandler:
    def __init__(self):
        self.active_transactions = {} # Key: src_id
        import threading
        self.lock = threading.Lock()
        
    def start_transaction(self, src_id, file_id, size, packets, crc):
        # Abort existing if any
        if src_id in self.active_transactions:
            self.active_transactions[src_id].cleanup()
            
        tx = FileTransaction(src_id, file_id, size, packets, crc)
        self.active_transactions[src_id] = tx
        return tx
        
    def get_transaction(self, src_id):
        return self.active_transactions.get(src_id)
        
    def end_transaction(self, src_id):
        if src_id in self.active_transactions:
            del self.active_transactions[src_id]

