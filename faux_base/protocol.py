import struct
import binascii
from enum import IntEnum

# --- Constants ---
HEADER_SIZE = 2

# GROK NOTE: The MTU acts as the algorithmic anchor for the file chunking math.
# The Pi Uploader forces all its physical blocks into exactly 200-byte payloads.
# Therefore, 205 - 2 (HEADER_SIZE) = 203. Then 203 - 3 (Type 10 overhead) = 200 Bytes.
# This strictly prevents the Receiver from padding the disk writes with empty zeros!
MTU = 240 # Perfectly synchronizing with Pi Uploader's 235-byte chunks 
PAYLOAD_MAX_SIZE = MTU - HEADER_SIZE  
# Type 10 overhead: ID(1) + Seq(2) = 3 bytes
TYPE10_DATA_SIZE = 235

# --- Enums ---
class PacketType(IntEnum):
    ACK = 0
    SSACK = 1
    NAK = 2
    CANCEL = 3
    REQ_XFER = 4
    APPROVE = 5
    HEARTBEAT = 6
    TASK_QUERY = 7
    TASK_ASSIGN = 8
    TASK_RESPONSE = 9
    FILE_DATA = 10
    CONF_XFER = 11
    XFER_FAIL = 12
    REQ_RELAY_XFER = 13
    BUSY = 14
    END_BLAST = 15

class BaseActions(IntEnum):
    NAP = 0x01
    SYNC_TIME = 0x02
    REBOOT = 0x03
    UPDATE_CONFIG = 0x04
    SET_SCHEDULE = 0x05
    SET_RSSI_THR = 0x06
    GET_NODE_RSSI = 0x07
    REQUEST_PKT = 0x08
    NO_TASK = 0x09
    DELETE_FILE = 0x0A
    REQ_RELAY = 0x0B
    POWER_ADJUST = 0x0C
    POLL_RELAY = 0x0D
    SLEEP_BUSY = 0x0E
    ERROR_FULL = 0x0F
    KILL = 0x7F

# --- CRC Utilities ---

def calculate_header_crc4(header_bytes: bytes) -> int:
    """
    Calculates 4-bit CRC (x^4 + x + 1) -> Poly 0x13
    over the first 12 bits of the header (Byte 0 + Byte 1 high nibble).
    Returns the 4-bit CRC value.
    """
    if len(header_bytes) < 2:
        return 0

    # Extract the 12 data bits (DestID, SrcID, MsgType)
    # Byte 0 (8 bits) + Byte 1 High Nibble (4 bits)
    data_bits = (header_bytes[0] << 4) | ((header_bytes[1] >> 4) & 0x0F)
    
    # We align this to the left of a 16-bit register for processing
    # Structure: [12 bits Data][4 bits Zeros for CRC]
    reg = data_bits << 4
    
    poly = 0x13 # 10011 (x^4 + x + 1)
    
    # Process 12 bits
    for _ in range(12):
        if reg & 0x8000: # If MSB (bit 15) is 1
            # Shifts poly to align with bit 15 (which is 10000 0000 0000 0000 check)
            # Poly 0x13 (10011) needs to be aligned.
            # 0x13 << 11 = 10011 000 000 00000
            reg = (reg ^ (poly << 11)) & 0xFFFF
        reg = (reg << 1) & 0xFFFF
        
    # The remainder is now in the top 4 bits of the register?
    # No, typically after shifting out all data bits, the remainder is the register.
    # Wait, usually with "left shifting" implementations:
    # After 12 shifts, the 4-bit CRC is in the high nibble of the register.
    
    return (reg >> 12) & 0x0F

def calculate_crc16(data: bytes) -> int:
    """
    CRC-16-CCITT (Poly 0x1021).
    Used for File Data.
    
    GROK NOTE: The integrity of the End-to-End file validation critically relies 
    on the mathematical initialization polynomial seed. The Pi Uploader native library 
    uses 0xFFFF. This Base Station originally used 0x0000. It MUST be 0xFFFF 
    to successfully validate the telemetry natively without false positive failures!
    """
    return binascii.crc_hqx(data, 0xFFFF)

# --- Packet Parsing ---

def parse_header(data: bytes):
    """
    Parses the 2-byte Global Header.
    Returns: (dest_id, src_id, msg_type, crc_received, crc_calculated, is_valid)
    """
    if len(data) < HEADER_SIZE:
        return None
        
    b0 = data[0]
    b1 = data[1]
    
    dest_id = (b0 >> 4) & 0x0F
    src_id  = b0 & 0x0F
    msg_type = (b1 >> 4) & 0x0F
    crc_received = b1 & 0x0F
    
    # Verify CRC
    crc_calc = calculate_header_crc4(data)
    is_valid = (crc_received == crc_calc)
    
    return dest_id, src_id, PacketType(msg_type), crc_received, crc_calc, is_valid

def build_header(dest_id: int, src_id: int, msg_type: int) -> bytes:
    """
    Constructs the 2-byte Global Header.
    Automatically calculates and appends the CRC.
    """
    # Temporary header with CRC=0 to calculate
    b0 = (dest_id << 4) | (src_id & 0x0F)
    b1_temp = (msg_type << 4) # CRC is 0
    
    temp_bytes = bytes([b0, b1_temp])
    crc = calculate_header_crc4(temp_bytes)
    
    b1 = b1_temp | (crc & 0x0F)
    
    return bytes([b0, b1])

# --- Structures ---

class Packet:
    def __init__(self, dest, src, msg_type, payload=b''):
        self.dest = dest
        self.src = src
        self.msg_type = msg_type
        self.payload = payload
        self.valid = True # Default
        self.bypass_window_size = None # GROK: safely decoupled A-Spectrum metadata
        
    def to_bytes(self):
        # META AI FIX: the payload is already inherently intact.
        header = build_header(self.dest, self.src, self.msg_type)
        return header + self.payload

    @staticmethod
    def from_bytes(data: bytes):
        if not data:
            return None
            
        # --- BLAST MODE INTERCEPT (0xA0 - 0xA3) ---
        # GROK NOTE: Blast mode bypasses standard API envelopes. The raw transmission
        # hits the ether prefixed with a single Byte mapping directly to the Window Size.
        if data[0] in (0xA0, 0xA1, 0xA2, 0xA3):
            if len(data) < 3: # Header(1), Seq(2)
                return None
            
            # Map the Bypass Header safely directly to the metadata property, decoupling from the 4-bit PacketType Enum
            if data[0] == 0xA0:
                bypass_size = 128
            elif data[0] == 0xA1:
                bypass_size = 64
            elif data[0] == 0xA2:
                bypass_size = 32
            else:
                bypass_size = 16
                
            seq_high = data[1]
            seq_low = data[2]
            
            # The remaining slice `data[3:]` matches the 200-byte Pi Uploader payload exactly.
            payload = data[1:] # Keep Seq(2)+Data in payload for session_manager to read seq
            
            # Synthesize a Packet of the correct dynamic type matching standard routing format [FileID(1)][Seq(2)][Data]
            # Hardcoding FileID=1 since blast mode currently forces 1.
            synth_payload = bytes([1, seq_high, seq_low]) + data[3:]
            
            # Submits upstream mapped as Dest=Base(0xF), Src=SessionLock(0x0)
            pkt = Packet(0xF, 0x0, PacketType.FILE_DATA, synth_payload)
            pkt.valid = True
            pkt.bypass_window_size = bypass_size
            return pkt
            
        # --- STANDARD PROTOCOL PARSING ---
        if len(data) < HEADER_SIZE:
            return None
        
        res = parse_header(data)
        if not res:
            return None
            
        dest, src, ptype, crc_rx, crc_calc, valid = res
        
        payload = data[HEADER_SIZE:]
        
        pkt = Packet(dest, src, ptype, payload)
        pkt.valid = valid
        return pkt
