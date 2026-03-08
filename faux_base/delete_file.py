import sys
import logging
import time
import re
from digi.xbee.devices import XBeeDevice
from digi.xbee.serial import FlowControl
from protocol import Packet, PacketType, BaseActions

# Config
XBEE_PORT = "/dev/ttyUSB0"
BAUD_RATE = 230400

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def parse_filename(filename):
    """
    Expects format like: A0038_IMG0004_SZ4512345.AVIF
    Or just: IMG0004_SZ4512345.JPG
    """
    m = re.search(r'(IMG\d+)_SZ(\d+)', filename, re.IGNORECASE)
    if not m:
        return None, None
    base_name = m.group(1) + ".JPG"
    expected_size = int(m.group(2))
    return base_name, expected_size

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 delete_file.py <avif_filename>")
        print("Example: python3 delete_file.py 123456_IMG0004_SZ4512345.AVIF")
        sys.exit(1)
        
    target_file = sys.argv[1]
    cam_file, expected_size = parse_filename(target_file)
    
    if not cam_file:
        print(f"Error: Could not parse original filename and SZ token from '{target_file}'")
        sys.exit(1)
        
    print(f"Targeting Camera File: {cam_file} (Expected Size: {expected_size} bytes)")
    
    device = XBeeDevice(XBEE_PORT, BAUD_RATE, flow_control=FlowControl.HARDWARE_RTS_CTS)
    try:
        device.open()
        device.set_parameter("PL", bytearray([0]))
        device.set_parameter("TR", bytearray([1])) 
        print(f"Listening on {XBEE_PORT} for Mule heartbeat...")
        
        target_mule_id = None
        
        def data_callback(xbee_message):
            nonlocal target_mule_id
            pkt = Packet.from_bytes(xbee_message.data)
            if pkt and pkt.msg_type == PacketType.HEARTBEAT:
                target_mule_id = pkt.src
                print(f"Heard Mule {pkt.src} heartbeat. Responding with SSACK.")
                # Send SSACK
                ack = Packet(pkt.src, 0xF, PacketType.SSACK, b'').to_bytes()
                device.send_data(xbee_message.remote_device, ack)
            elif pkt and pkt.msg_type == PacketType.TASK_QUERY:
                if target_mule_id == pkt.src:
                    print(f"Mule {pkt.src} is soliciting tasks. Transmitting DELETE payload...")
                    # Build Payload
                    payload_str = f"{cam_file}|{expected_size}".encode('utf-8')
                    # Payload = [Action(1)][Token(1)][Len(1)][Data(N)]
                    task_payload = bytes([BaseActions.DELETE_FILE, 0x99, len(payload_str)]) + payload_str
                    
                    assign = Packet(pkt.src, 0xF, PacketType.TASK_ASSIGN, task_payload).to_bytes()
                    device.send_data(xbee_message.remote_device, assign)
            elif pkt and pkt.msg_type == PacketType.TASK_RESPONSE:
                if len(pkt.payload) >= 3 and pkt.payload[0] == BaseActions.DELETE_FILE:
                    status = pkt.payload[2]
                    if status == 0x00:
                        print(f"SUCCESS: Mule reported file '{cam_file}' was mathematically verified and permanently deleted from camera.")
                        sys.exit(0)
                    else:
                        print(f"FAILURE: Mule failed to delete '{cam_file}'. Size mismatch or camera unreachable.")
                        sys.exit(1)
        
        device.add_data_received_callback(data_callback)
        
        # Wait up to 60 seconds
        start_time = time.time()
        while time.time() - start_time < 60:
            time.sleep(0.1)
            
        print("Timeout: No Mule heartbeat detected within 60 seconds.")
        sys.exit(1)
            
    except SystemExit:
        pass
    except Exception as e:
        print(f"XBee Error: {e}")
    finally:
        if device.is_open():
            device.close()

if __name__ == "__main__":
    main()
