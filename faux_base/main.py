import logging
import time
import sys
import signal
from digi.xbee.devices import XBeeDevice
from digi.xbee.serial import FlowControl
from session_manager import SessionManager

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Configuration
XBEE_PORT_CMD = "/dev/ttyUSB0"
XBEE_PORT_DATA = "/dev/ttyUSB1"
BAUD_RATE = 230400

def main():
    logging.info("Starting Faux Base Station...")
    
    # META AI FIX: Patch XBee Queue Size to prevent 200 Kbps 0.014s payload drops!
    try:
        import digi.xbee.reader as xbee_reader
        xbee_reader.PacketListener._PacketListener__DEFAULT_QUEUE_MAX_SIZE = 5000
    except Exception as e:
        logging.warning(f"Failed to patch XBee Max Queue Size: {e}")
    
    # Pre-flight cleanup: Remove stale diagnostic chunks so file_handler.py 
    # doesn't append to an old ghost file padding error.
    try:
        import os
        received_dir = os.path.join(os.path.dirname(__file__), "received_files")
        if os.path.exists(received_dir):
            for f in os.listdir(received_dir):
                if f.startswith("node"):
                    os.remove(os.path.join(received_dir, f))
            logging.info("Cleared stale receiver chunks from /received_files/")
    except Exception as e:
        logging.warning(f"Failed to clear received files: {e}")

    # Initialize XBee Devices for Dual-Radio Sync
    managers = []
    
    try:
        # Command Lane (10K)
        logging.info(f"Binding Command Transceiver: {XBEE_PORT_CMD}")
        device_cmd = XBeeDevice(XBEE_PORT_CMD, BAUD_RATE, flow_control=FlowControl.HARDWARE_RTS_CTS)
        mgr_cmd = SessionManager(device_cmd, is_data_lane=False)
        managers.append(mgr_cmd)
        
        # High-Speed Data Lane (200K)
        import os
        if os.path.exists(XBEE_PORT_DATA):
            logging.info(f"Binding Payload Transceiver: {XBEE_PORT_DATA}")
            device_data = XBeeDevice(XBEE_PORT_DATA, BAUD_RATE, flow_control=FlowControl.HARDWARE_RTS_CTS)
            mgr_data = SessionManager(device_data, is_data_lane=True)
            managers.append(mgr_data)
        else:
            logging.warning(f"Dual-Radio degraded! {XBEE_PORT_DATA} not found. Operating in Single Radio Mode.")
    except Exception as e:
        logging.error(f"Hardware initialization failed: {e}")
        return

    try:
        for mgr in managers:
            mgr.start()
            
        while any(mgr.running for mgr in managers):
            time.sleep(1)
            
    except KeyboardInterrupt:
        logging.info("Stopping Faux Base Cluster...")
    except Exception as e:
        logging.error(f"Unexpected Error: {e}")
    finally:
        for mgr in managers:
            mgr.stop()
        logging.info("Exited Cleanly.")

if __name__ == "__main__":
    main()
