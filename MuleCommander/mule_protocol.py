import struct
import binascii
from enum import IntEnum

# --- Constants ---
HEADER_SIZE = 2
MTU = 240
PAYLOAD_MAX_SIZE = MTU - HEADER_SIZE  # 98 bytes available for payload
# Type 10 overhead: ID(1) + Seq(2) = 3 bytes
# Type 10 overhead: ID(1) + Seq(2) = 3 bytes
TYPE10_DATA_SIZE = PAYLOAD_MAX_SIZE - 3

# Blast Mode Overhead: Marker(1) + Seq(2) = 3 bytes
# Actually, could be Marker(1) + Seq(2) = 3.
# Or just Seq(2)? User wants MINIMAL.
# We need Marker to distinguish from Frame Type?
# No, XBee RX packet gives us the payload.
# If we are in "Blast State", we treat all 0x10 frames as data?
# But we need to distinguish END_BLAST?
# Best to have a 1-byte marker for everything?
# Or just Packet vs Raw?
# Sender uses TransmitPacket.
# We will use [0xAA][Seq][Data].
BLAST_PAYLOAD_SIZE = MTU - 3 # 0xAA + Seq(2)

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
    # REQ_BLAST: Reuse REQ_XFER (4) with flag
    END_BLAST = 15 # Max 4-bit value

# Raw Data Marker for Blast Mode (1 byte)
BLAST_DATA_HEADER = 0xAA

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
        
    def to_bytes(self):
        header = build_header(self.dest, self.src, self.msg_type)
        return header + self.payload

    @staticmethod
    def from_bytes(data: bytes):
        if len(data) < 1:
            return None
            
        # Blast Mode Optimisation
        if data[0] == BLAST_DATA_HEADER:
            # Skip Header Parsing and CRC
            # Payload is everything after 0xAA
            # We assume Src/Dest are irrelevant (Session Locked)
            # We map it to FILE_DATA type
            return Packet(0, 0, PacketType.FILE_DATA, data[1:])
            
        if len(data) < HEADER_SIZE:
            return None
        
        # We process even if CRC fail? No, usually we drop.
        # But this method just parses.
        res = parse_header(data)
        if not res:
            return None
            
        dest, src, ptype, crc_rx, crc_calc, valid = res
        
        # Slicing bytes safely
        payload = data[HEADER_SIZE:]
        
        pkt = Packet(dest, src, ptype, payload)
        pkt.valid = valid
        return pkt
